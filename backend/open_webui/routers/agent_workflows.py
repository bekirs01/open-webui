"""
Multi-agent workflow orchestration — n8n-style blocks (trigger, agent, if_else, transform) + DAG DFS.
"""

import asyncio
import copy
import json
import logging
import time
from collections import defaultdict, deque
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from open_webui.models.users import UserModel
from open_webui.utils.auth import get_verified_user
from open_webui.utils.mws_gpt.router import LEGACY_AUTO_IDS
from open_webui.workflow_expr import (
    ExprContext,
    evaluate_expression,
    substitute_template,
    wire_items_to_json_list,
)
from open_webui.workflow_ssrf import validate_public_http_url
from open_webui.workflow_wire import (
    branch_from_if_output,
    eval_if_json_compare,
    get_by_path,
    make_wire,
    parse_wire,
    substitute_step_templates,
    wire_display_text,
    wire_for_llm_context,
    wrap_agent_text_reply,
    wrap_http_result,
    wrap_if_result,
    wrap_trigger,
)

log = logging.getLogger(__name__)

router = APIRouter()


class AgentDef(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    name: str = ''
    modelId: str = Field(alias='modelId')


class WorkflowNode(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='ignore')
    id: str
    nodeType: str = Field(default='agent', alias='nodeType')
    agentId: str = Field(default='', alias='agentId')
    agentName: str = Field(default='', alias='agentName')
    modelId: str = Field(default='', alias='modelId')
    task: str = ''
    mode: str = 'text'
    config: Optional[dict[str, Any]] = None
    position: Optional[dict[str, Any]] = None


class WorkflowEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    fromNodeId: str = Field(alias='fromNodeId')
    toNodeId: str = Field(alias='toNodeId')
    sourceHandle: Optional[str] = Field(default=None, alias='sourceHandle')
    disabled: Optional[bool] = None
    when: Optional[str] = Field(default=None, alias='when')


class WorkflowPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='ignore')
    version: int = 1
    startNodeId: str = Field(alias='startNodeId')
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]


class RunBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    user_input: str = ''
    workflow: dict
    agents: list[AgentDef]
    image_prompt_refine_model: Optional[str] = Field(default=None, alias='image_prompt_refine_model')


def _reachable_from(start: str, adj: dict[str, list[str]]) -> set[str]:
    seen = set()
    dq = deque([start])
    while dq:
        u = dq.popleft()
        if u in seen:
            continue
        seen.add(u)
        for v in adj.get(u, []):
            if v not in seen:
                dq.append(v)
    return seen


def _topo_order(nodes: list[WorkflowNode], edges: list[WorkflowEdge], start_id: str) -> list[str]:
    node_ids = {n.id for n in nodes}
    if start_id not in node_ids:
        raise ValueError('startNodeId does not match any node')

    adj: dict[str, list[str]] = defaultdict(list)
    incoming_to_start = 0
    for e in edges:
        if e.disabled:
            continue
        if e.fromNodeId in node_ids and e.toNodeId in node_ids:
            adj[e.fromNodeId].append(e.toNodeId)
            if e.toNodeId == start_id:
                incoming_to_start += 1
    if incoming_to_start:
        raise ValueError('start node must not have incoming edges')

    reachable = _reachable_from(start_id, adj)
    if not reachable:
        raise ValueError('no nodes reachable from start')

    indeg = {nid: 0 for nid in reachable}
    sub_adj: dict[str, list[str]] = defaultdict(list)
    for u in reachable:
        for v in adj[u]:
            if v in reachable:
                sub_adj[u].append(v)
                indeg[v] = indeg.get(v, 0) + 1

    roots = sorted([u for u in reachable if indeg.get(u, 0) == 0])
    if start_id not in roots:
        raise ValueError('start node is not a source of the workflow subgraph')
    other_roots = [u for u in roots if u != start_id]
    queue: deque[str] = deque([start_id] + other_roots)
    order: list[str] = []
    while queue:
        u = queue.popleft()
        order.append(u)
        for v in sorted(sub_adj[u]):
            indeg[v] -= 1
            if indeg[v] == 0:
                queue.append(v)

    if len(order) != len(reachable):
        raise ValueError('workflow graph has a cycle or invalid edges')
    return order


async def _call_chat_completion(
    request: Request,
    auth_header: Optional[str],
    model_id: str,
    messages: list[dict],
) -> str:
    base = str(request.base_url).rstrip('/')
    url = f'{base}/api/chat/completions'
    payload = {
        'model': model_id,
        'messages': messages,
        'stream': False,
    }
    headers = {'Content-Type': 'application/json'}
    if auth_header:
        headers['Authorization'] = auth_header

    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0)) as client:
        r = await client.post(url, headers=headers, json=payload)

    if r.status_code >= 400:
        try:
            detail = r.json()
            msg = detail.get('detail', detail) if isinstance(detail, dict) else str(detail)
        except Exception:
            msg = r.text or str(r.status_code)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f'LLM call failed: {msg}')

    data = r.json()
    try:
        return (data.get('choices') or [{}])[0].get('message', {}).get('content') or ''
    except Exception:
        log.warning('Unexpected chat completion shape: %s', data)
        return json.dumps(data)[:2000]


def _extract_text_for_next_step(result: str) -> str:
    """Human-facing short text from any step output (wire or legacy)."""
    return wire_display_text(parse_wire(result))


async def _refine_image_prompt(
    request: Request,
    auth_header: Optional[str],
    model_id: str,
    task_instruction: str,
    user_input: str,
    prior_output: str,
) -> str:
    messages = [
        {
            'role': 'system',
            'content': (
                'You are preparing input for an image generation API. '
                'Follow the instruction below and output ONLY the final image prompt text, '
                'with no quotes or preamble.\n\n'
                f'Instruction:\n{task_instruction}'
            ),
        },
        {
            'role': 'user',
            'content': (
                f'Initial user request:\n{user_input.strip() or "(none)"}\n\n'
                f'Output from the previous workflow step (JSON wire):\n'
                f'{wire_for_llm_context(prior_output) or "(none)"}'
            ),
        },
    ]
    return (await _call_chat_completion(request, auth_header, model_id, messages)).strip()


def _image_model_for_generations_request(model_id: str) -> Optional[str]:
    m = (model_id or '').strip()
    if not m or m in LEGACY_AUTO_IDS:
        return None
    return m


async def _call_image_generations(
    request: Request,
    auth_header: Optional[str],
    model_id: str,
    prompt: str,
) -> list[dict[str, Any]]:
    base = str(request.base_url).rstrip('/')
    url = f'{base}/api/v1/images/generations'
    payload: dict[str, Any] = {'prompt': prompt, 'n': 1}
    effective = _image_model_for_generations_request(model_id)
    if effective:
        payload['model'] = effective
    headers = {'Content-Type': 'application/json'}
    if auth_header:
        headers['Authorization'] = auth_header

    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0)) as client:
        r = await client.post(url, headers=headers, json=payload)

    if r.status_code >= 400:
        try:
            detail = r.json()
            msg = detail.get('detail', detail) if isinstance(detail, dict) else str(detail)
        except Exception:
            msg = r.text or str(r.status_code)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f'Image generation failed: {msg}',
        )

    data = r.json()
    if not isinstance(data, list):
        log.warning('Unexpected image generations response: %s', data)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail='Image generation returned an unexpected response',
        )
    return data


def _absolute_url(request: Request, path: str) -> str:
    if path.startswith('http://') or path.startswith('https://'):
        return path
    base = str(request.base_url).rstrip('/')
    if not path.startswith('/'):
        path = '/' + path
    return base + path


def _build_out_edges(edges: list[WorkflowEdge]) -> dict[str, list[WorkflowEdge]]:
    out_map: dict[str, list[WorkflowEdge]] = defaultdict(list)
    for e in edges:
        out_map[e.fromNodeId].append(e)
    return out_map


def _build_parents_map(edges: list[WorkflowEdge], node_ids: set[str]) -> dict[str, list[str]]:
    pm: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        if e.fromNodeId not in node_ids or e.toNodeId not in node_ids:
            continue
        if e.disabled:
            continue
        pm[e.toNodeId].append(e.fromNodeId)
    return {k: sorted(set(v)) for k, v in pm.items()}


def _terminal_node_ids(node_ids: set[str], edges: list[WorkflowEdge]) -> set[str]:
    has_out: set[str] = set()
    for e in edges:
        if e.disabled:
            continue
        if e.fromNodeId in node_ids and e.toNodeId in node_ids:
            has_out.add(e.fromNodeId)
    return node_ids - has_out


def _validate_if_else_edges(nodes: list[WorkflowNode], edges: list[WorkflowEdge], node_ids: set[str]) -> None:
    if_else_ids = {n.id for n in nodes if (n.nodeType or 'agent').lower() == 'if_else'}
    for e in edges:
        if e.disabled:
            continue
        if e.fromNodeId not in if_else_ids:
            continue
        if e.fromNodeId not in node_ids or e.toNodeId not in node_ids:
            continue
        sh = (e.sourceHandle or '').strip().lower()
        if sh not in ('true', 'false'):
            raise ValueError(
                f'IF node "{e.fromNodeId}" edge to "{e.toNodeId}" must set sourceHandle to '
                f'"true" or "false" (got {e.sourceHandle!r})'
            )


def _workflow_error_wire(node_id: str, message: str) -> str:
    return make_wire(
        [
            {
                'json': {
                    'type': 'workflow_error',
                    'error': True,
                    'message': (message or '')[:8000],
                    'nodeId': node_id,
                }
            }
        ],
        text=(message or '')[:12000],
    )


def _terminal_wire_to_markdown(last_raw: str) -> str:
    """Human-facing markdown for one terminal node's wire (image/http get richer blocks)."""
    final_text = wire_display_text(parse_wire(last_raw)) or last_raw
    try:
        w = parse_wire(last_raw)
        items = w.get('items') or []
        j0 = (items[0].get('json') if items and isinstance(items[0], dict) else {}) or {}
        if isinstance(j0, dict) and j0.get('type') == 'image_result':
            prompt = j0.get('prompt') or ''
            urls = j0.get('urls') or []
            lines = [f'**Image prompt:** {prompt}', '']
            for u in urls:
                lines.append(f'![generated]({u})')
            return '\n'.join(lines)
        if isinstance(j0, dict) and j0.get('type') == 'http_result':
            sc = j0.get('statusCode')
            u = j0.get('url') or ''
            b = j0.get('body') or ''
            err = j0.get('error')
            head = f'**HTTP** {sc if sc is not None else "?"} `{u}`'
            if err:
                return f'{head}\n\n```\n{err}\n```'
            preview = (b or '')[:12000]
            return f'{head}\n\n```\n{preview}\n```'
    except Exception:
        pass
    return final_text


def _build_final_markdown_from_terminals(terminal_ids: set[str], results: dict[str, str]) -> str:
    parts: list[str] = []
    for tid in sorted(terminal_ids):
        if tid not in results:
            continue
        block = _terminal_wire_to_markdown(results[tid])
        parts.append(f'### `{tid}`\n\n{block}\n')
    return '\n'.join(parts).strip()


def _normalize_wire_item_entry(it: Any) -> dict[str, Any]:
    """Normalize to { 'json': dict } with deep-copied json (merge / IF safe)."""
    if isinstance(it, dict) and isinstance(it.get('json'), dict):
        return {'json': copy.deepcopy(it['json'])}
    if isinstance(it, dict):
        return {'json': copy.deepcopy(it)}
    return {'json': {}}


def _eval_if_on_single_item(
    norm: dict[str, Any],
    cfg: dict[str, Any],
    *,
    batch_json_list: list[dict[str, Any]],
    item_index: int,
) -> bool:
    """Evaluate IF for one wire row: expression (preferred) or legacy json/substring."""
    expr = str(cfg.get('conditionExpression') or cfg.get('expression') or '').strip()
    if expr:
        j = norm.get('json') if isinstance(norm.get('json'), dict) else {}
        ctx = ExprContext(json=j, item_index=item_index, input=batch_json_list)
        return bool(evaluate_expression(expr, ctx))

    mode = str(cfg.get('conditionMode') or 'substring').strip().lower()
    mini = make_wire([norm], text='')
    if mode in ('json', 'json_compare'):
        jp = str(cfg.get('jsonPath') or '').strip()
        op = str(cfg.get('jsonOperator') or 'equals').strip()
        cv = str(cfg.get('compareValue') or '')
        return eval_if_json_compare(mini, json_path=jp, operator=op, compare_value=cv)
    cond = str(cfg.get('condition', '') or '').strip()
    prior_text = wire_display_text(parse_wire(mini))
    return (cond.lower() in prior_text.lower()) if cond else False


@router.post('/run')
async def run_workflow(
    request: Request,
    body: RunBody,
    user: UserModel = Depends(get_verified_user),
):
    _ = user
    try:
        wf = WorkflowPayload.model_validate(body.workflow)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f'Invalid workflow: {e}') from e

    node_by_id = {n.id: n for n in wf.nodes}
    node_ids = set(node_by_id.keys())
    agents_by_id = {a.id: a for a in body.agents}

    try:
        _topo_order(wf.nodes, wf.edges, wf.startNodeId)
        _validate_if_else_edges(wf.nodes, wf.edges, node_ids)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    terminal_ids = _terminal_node_ids(node_ids, wf.edges)
    parents_map = _build_parents_map(wf.edges, node_ids)

    out_map = _build_out_edges(wf.edges)

    auth_header = request.headers.get('authorization') or request.headers.get('Authorization')

    results: dict[str, str] = {}
    logs: list[dict[str, Any]] = []
    execution_order: list[str] = []
    visit_stack: set[str] = set()
    run_state: dict[str, Any] = {
        'halted': False,
        'failed_node_id': None,
        'failed_error': None,
    }

    def _fail_run(nid: str, message: str) -> None:
        run_state['halted'] = True
        run_state['failed_node_id'] = nid
        run_state['failed_error'] = (message or '')[:8000]
        if nid not in results:
            results[nid] = _workflow_error_wire(nid, message)

    def _finish_node_metrics(nid: str, log_entry: dict[str, Any], t0: float, in_sz: int) -> None:
        log_entry['durationMs'] = int((time.perf_counter() - t0) * 1000)
        log_entry['inputSize'] = in_sz
        log_entry['outputSize'] = len(results.get(nid, ''))

    def _log_node(nid: str, entry: dict[str, Any], *, t0: float, in_sz: int) -> None:
        _finish_node_metrics(nid, entry, t0, in_sz)
        logs.append(entry)

    def _active_out_edges(from_id: str) -> list[WorkflowEdge]:
        return sorted(
            [e for e in out_map.get(from_id, []) if not (e.disabled or False)],
            key=lambda x: x.toNodeId,
        )

    def _has_agent_failure_route(from_id: str) -> bool:
        for e in _active_out_edges(from_id):
            w = (e.when or 'always').strip().lower()
            if w in ('on_error', 'always'):
                return True
        return False

    async def _follow_edges(
        from_id: str, node_kind: str, *, agent_ok: Optional[bool] = None
    ) -> None:
        outs = _active_out_edges(from_id)
        if not outs:
            return
        nk = (node_kind or 'agent').lower()
        if nk == 'if_else':
            br = branch_from_if_output(results.get(from_id, ''))
            want = 'true' if br else 'false'
            for e in outs:
                sh = (e.sourceHandle or '').strip().lower()
                if sh not in ('true', 'false'):
                    raise ValueError(
                        f'IF node "{from_id}" edge to "{e.toNodeId}" has invalid sourceHandle '
                        f'(expected "true" or "false", got {e.sourceHandle!r})'
                    )
                if sh == want:
                    await dfs_execute(e.toNodeId)
            return
        if nk == 'agent' and agent_ok is not None:
            for e in outs:
                w = (e.when or 'always').strip().lower()
                if agent_ok:
                    if w == 'on_error':
                        continue
                else:
                    if w not in ('on_error', 'always'):
                        continue
                await dfs_execute(e.toNodeId)
            return
        for e in outs:
            w = (e.when or 'always').strip().lower()
            if w == 'on_error':
                continue
            await dfs_execute(e.toNodeId)

    async def _execute_agent_step(
        nid: str,
        node: WorkflowNode,
        prior_wire: str,
        parent_id: Optional[str],
        *,
        metrics_t0: Optional[float] = None,
        metrics_input_sz: Optional[int] = None,
    ) -> str:
        """Run agent LLM/image step only (no downstream traversal). Returns success, routed_error, or fatal."""

        def _agent_log(entry: dict[str, Any]) -> None:
            if metrics_t0 is not None:
                _finish_node_metrics(nid, entry, metrics_t0, metrics_input_sz or 0)
            logs.append(entry)

        cfg = node.config or {}
        retries = max(0, int(cfg.get('retries') or 0))
        delay_ms = max(0, int(cfg.get('retryDelayMs') or 0))

        aid = (node.agentId or '').strip() or nid
        agent = agents_by_id.get(aid)
        if not agent:
            msg = f'Unknown agent id for node {nid}: {aid}'
            results[nid] = _workflow_error_wire(nid, msg)
            _agent_log(
                {
                    'nodeId': nid,
                    'nodeType': 'agent',
                    'error': True,
                    'detail': msg,
                    'outputPreview': msg[:500],
                }
            )
            _fail_run(nid, msg)
            return 'fatal'
        model_id = (agent.modelId or '').strip()
        if not model_id:
            msg = f'Agent {aid} has no modelId'
            results[nid] = _workflow_error_wire(nid, msg)
            _agent_log(
                {
                    'nodeId': nid,
                    'nodeType': 'agent',
                    'error': True,
                    'detail': msg,
                    'outputPreview': msg[:500],
                }
            )
            _fail_run(nid, msg)
            return 'fatal'
        task = (node.task or '').strip()
        node_mode = (node.mode or 'text').strip().lower()
        if node_mode not in ('text', 'image'):
            node_mode = 'text'

        prior_text = wire_display_text(parse_wire(prior_wire)) if parent_id else ''
        prev_summary_ctx = wire_for_llm_context(prior_wire) if parent_id else ''

        last_exc: Optional[HTTPException] = None
        for attempt in range(retries + 1):
            try:
                if node_mode == 'image':
                    prior_raw = prior_wire if parent_id else body.user_input.strip()
                    if task:
                        refine_chat_model = (body.image_prompt_refine_model or '').strip() or model_id
                        image_prompt = await _refine_image_prompt(
                            request,
                            auth_header,
                            refine_chat_model,
                            task,
                            body.user_input,
                            prior_raw,
                        )
                    else:
                        image_prompt = (
                            prior_text.strip() or body.user_input.strip() or 'image'
                        )

                    img_list = await _call_image_generations(request, auth_header, model_id, image_prompt)
                    urls: list[str] = []
                    for item in img_list:
                        if isinstance(item, dict) and item.get('url'):
                            urls.append(_absolute_url(request, str(item['url'])))

                    result_obj = {
                        'type': 'image_result',
                        'prompt': image_prompt,
                        'urls': urls,
                    }
                    results[nid] = make_wire(
                        [{'json': result_obj}],
                        text=image_prompt or '',
                    )
                    _agent_log(
                        {
                            'nodeId': nid,
                            'nodeType': 'agent',
                            'agentId': aid,
                            'modelId': model_id,
                            'task': task,
                            'mode': 'image',
                            'imagePrompt': image_prompt,
                            'imageUrls': urls,
                            'outputPreview': (image_prompt or '')[:200],
                            'attempt': attempt + 1,
                        }
                    )
                else:
                    user_block = (
                        f'User request:\n{body.user_input.strip() or "(no text)"}\n\n'
                        f'Input from previous step:\n{prev_summary_ctx or "(none)"}\n\n'
                        f'Your step instruction:\n{task or "(execute helpfully)"}'
                    )
                    messages = [
                        {
                            'role': 'system',
                            'content': (
                                'You are one step in a multi-agent workflow. '
                                'Follow the step instruction; reply concisely.'
                            ),
                        },
                        {'role': 'user', 'content': user_block},
                    ]
                    text = await _call_chat_completion(request, auth_header, model_id, messages)
                    results[nid] = wrap_agent_text_reply(text)
                    _agent_log(
                        {
                            'nodeId': nid,
                            'nodeType': 'agent',
                            'agentId': aid,
                            'modelId': model_id,
                            'task': task,
                            'mode': 'text',
                            'outputPreview': (text or '')[:500],
                            'attempt': attempt + 1,
                        }
                    )
                return 'success'
            except HTTPException as e:
                last_exc = e
                if attempt < retries:
                    await asyncio.sleep(delay_ms / 1000.0)
                    continue
                err_obj = {'type': 'agent_error', 'status': e.status_code, 'detail': str(e.detail)}
                results[nid] = make_wire(
                    [{'json': err_obj}],
                    text=str(e.detail)[:4000],
                )
                _agent_log(
                    {
                        'nodeId': nid,
                        'nodeType': 'agent',
                        'error': True,
                        'status': e.status_code,
                        'detail': str(e.detail),
                        'outputPreview': str(e.detail)[:500],
                    }
                )
                if not _has_agent_failure_route(nid):
                    _fail_run(nid, str(e.detail))
                    return 'fatal'
                return 'routed_error'

        if last_exc:
            if not _has_agent_failure_route(nid):
                _fail_run(nid, str(last_exc.detail))
                return 'fatal'
            return 'routed_error'
        return 'success'

    async def dfs_execute(
        nid: str,
        incoming_items: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        if run_state['halted']:
            return
        if nid in results:
            return
        if incoming_items is not None and len(incoming_items) == 0:
            return
        node = node_by_id.get(nid)
        if not node:
            return

        nt = (node.nodeType or 'agent').lower()
        cfg = node.config or {}
        parents_list = parents_map.get(nid, [])

        if nt not in ('merge', 'group') and len(parents_list) > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Multiple incoming edges require a merge node.',
            )

        if nt == 'group':
            _gt0 = time.perf_counter()
            _gsz = 0
            results[nid] = make_wire([], text='')
            _log_node(
                nid,
                {
                    'nodeId': nid,
                    'nodeType': 'group',
                    'skipped': True,
                    'outputPreview': '(group)',
                },
                t0=_gt0,
                in_sz=_gsz,
            )
            execution_order.append(nid)
            await _follow_edges(nid, 'group')
            return

        if nt == 'merge':
            for p in parents_list:
                await dfs_execute(p)
            if nid in results:
                return
            if len(parents_list) < 2:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail='Merge node needs at least two incoming edges.',
                )
            _mt0 = time.perf_counter()
            _min_sz = sum(len(results.get(p, '')) for p in parents_list)
            sep = str((cfg or {}).get('separator') or '\n---\n')
            acc_items: list[dict[str, Any]] = []
            texts: list[str] = []
            for p in parents_list:
                w = parse_wire(results.get(p, ''))
                for it in w.get('items') or []:
                    if isinstance(it, dict) and isinstance(it.get('json'), dict):
                        acc_items.append({'json': copy.deepcopy(it['json'])})
                    elif isinstance(it, dict):
                        acc_items.append({'json': copy.deepcopy(it)})
                tx = w.get('text')
                if isinstance(tx, str) and tx.strip():
                    texts.append(tx)
                elif w.get('items'):
                    try:
                        texts.append(
                            json.dumps((w['items'][0] or {}).get('json') or {}, ensure_ascii=False)[
                                :4000
                            ]
                        )
                    except Exception:
                        texts.append('')
            joined_text = sep.join(texts) if sep else '\n'.join(texts)
            merged_str = make_wire(acc_items, text=joined_text)

            if cfg.get('disabled'):
                results[nid] = merged_str
                _log_node(
                    nid,
                    {
                        'nodeId': nid,
                        'nodeType': 'merge',
                        'skipped': True,
                        'outputPreview': '(disabled)',
                    },
                    t0=_mt0,
                    in_sz=_min_sz,
                )
                execution_order.append(nid)
                await _follow_edges(nid, nt)
                return

            results[nid] = merged_str
            _log_node(
                nid,
                {
                    'nodeId': nid,
                    'nodeType': 'merge',
                    'outputPreview': (joined_text or '')[:500],
                },
                t0=_mt0,
                in_sz=_min_sz,
            )
            execution_order.append(nid)
            await _follow_edges(nid, nt)
            return

        parent_id = parents_list[0] if len(parents_list) == 1 else None
        if incoming_items is not None:
            if parent_id and parent_id not in results:
                await dfs_execute(parent_id)
            norm_items = [_normalize_wire_item_entry(x) for x in incoming_items]
            prior_full = make_wire(norm_items, text='')
            prior_text = wire_display_text(parse_wire(prior_full))
            prev_summary_ctx = wire_for_llm_context(prior_full)
        else:
            if parent_id and parent_id not in results:
                await dfs_execute(parent_id)
            prior_full = results.get(parent_id, '') if parent_id else ''
            prior_text = wire_display_text(parse_wire(prior_full)) if parent_id else ''
            prev_summary_ctx = wire_for_llm_context(prior_full) if parent_id else ''

        if nid in visit_stack:
            raise ValueError('workflow execution hit a cycle')
        visit_stack.add(nid)
        _t_node = time.perf_counter()
        _input_sz = len(prior_full)
        try:
            if cfg.get('disabled'):
                if nt == 'trigger':
                    results[nid] = wrap_trigger(body.user_input.strip() or '')
                elif nt == 'if_else':
                    results[nid] = wrap_if_result(False)
                elif nt == 'transform':
                    results[nid] = prior_full if parent_id else wrap_trigger('')
                elif nt == 'http_request':
                    results[nid] = prior_full if parent_id else wrap_trigger(body.user_input.strip() or '')
                elif nt == 'agent':
                    results[nid] = (
                        prior_full
                        if parent_id
                        else wrap_trigger(body.user_input.strip() or '')
                    )
                else:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f'Unsupported nodeType: {nt}',
                    )
                _log_node(
                    nid,
                    {
                        'nodeId': nid,
                        'nodeType': nt,
                        'skipped': True,
                        'outputPreview': '(disabled)',
                    },
                    t0=_t_node,
                    in_sz=_input_sz,
                )
                execution_order.append(nid)
                await _follow_edges(nid, nt)
                return

            if nt == 'trigger':
                out = body.user_input.strip() or ''
                results[nid] = wrap_trigger(out)
                _log_node(
                    nid,
                    {
                        'nodeId': nid,
                        'nodeType': 'trigger',
                        'outputPreview': (out or '')[:500],
                    },
                    t0=_t_node,
                    in_sz=_input_sz,
                )
            elif nt == 'if_else':
                # Item-level IF (n8n-style): each input row evaluated independently; both branches may run.
                raw_items = parse_wire(prior_full).get('items') or []
                batch_json_list = wire_items_to_json_list(raw_items)
                true_items: list[dict[str, Any]] = []
                false_items: list[dict[str, Any]] = []
                mode = str(cfg.get('conditionMode') or 'substring').strip().lower()
                for idx, raw in enumerate(raw_items):
                    norm = _normalize_wire_item_entry(raw)
                    b = _eval_if_on_single_item(
                        norm,
                        cfg,
                        batch_json_list=batch_json_list,
                        item_index=idx,
                    )
                    (true_items if b else false_items).append(norm)
                tx = f'{len(true_items)} true / {len(false_items)} false'
                # Passthrough: output items mirror input payload (unchanged), counts in logs only.
                passthrough = [_normalize_wire_item_entry(r) for r in raw_items]
                results[nid] = make_wire(passthrough, text=tx)
                log_cond: dict[str, Any] = {
                    'conditionMode': mode,
                    'trueItemCount': len(true_items),
                    'falseItemCount': len(false_items),
                    'falseCount': len(false_items),
                    'trueCount': len(true_items),
                    'itemCount': len(raw_items),
                }
                cex = str(cfg.get('conditionExpression') or cfg.get('expression') or '').strip()
                if cex:
                    log_cond['conditionExpression'] = cex[:2000]
                elif mode in ('json', 'json_compare'):
                    jp = str(cfg.get('jsonPath') or '').strip()
                    log_cond['jsonPath'] = jp
                    log_cond['jsonOperator'] = str(cfg.get('jsonOperator') or 'equals').strip()
                    log_cond['compareValue'] = str(cfg.get('compareValue') or '')
                    wpeek = parse_wire(prior_full)
                    log_cond['resolvedPathValue'] = get_by_path(wpeek, jp) if jp else None
                else:
                    log_cond['condition'] = str(cfg.get('condition', '') or '').strip()
                _log_node(
                    nid,
                    {
                        'nodeId': nid,
                        'nodeType': 'if_else',
                        'outputPreview': tx[:200],
                        **log_cond,
                    },
                    t0=_t_node,
                    in_sz=_input_sz,
                )
                execution_order.append(nid)
                for e in _active_out_edges(nid):
                    sh = (e.sourceHandle or '').strip().lower()
                    if sh not in ('true', 'false'):
                        raise ValueError(
                            f'IF node "{nid}" edge to "{e.toNodeId}" has invalid sourceHandle '
                            f'(expected "true" or "false", got {e.sourceHandle!r})'
                        )
                    if sh == 'true' and true_items:
                        await dfs_execute(e.toNodeId, true_items)
                    elif sh == 'false' and false_items:
                        await dfs_execute(e.toNodeId, false_items)
                return
            elif nt == 'transform':
                w = parse_wire(prior_full)
                items = w.get('items') or []
                if not items:
                    items = [{}]
                tpl = str(cfg.get('template', '{{input}}'))
                ui = body.user_input.strip()
                all_jsons = wire_items_to_json_list(items)
                out_rows: list[dict[str, Any]] = []
                text_parts: list[str] = []
                for idx, item0 in enumerate(items):
                    j0 = item0.get('json') if isinstance(item0, dict) else {}
                    if not isinstance(j0, dict):
                        j0 = {}
                    row_wire = make_wire([{'json': j0}], text='')
                    pt_row = wire_display_text(parse_wire(row_wire))
                    json_snip = json.dumps(j0, ensure_ascii=False)
                    base = (
                        tpl.replace('{{input}}', pt_row)
                        .replace('{{INPUT}}', pt_row)
                        .replace('{{json}}', json_snip)
                        .replace('{{JSON}}', json_snip)
                        .replace('{{user_input}}', ui)
                        .replace('{{USER_INPUT}}', ui)
                    )
                    ctx = ExprContext(json=j0, item_index=idx, input=all_jsons)
                    out = substitute_template(base, ctx)
                    text_parts.append(out)
                    out_rows.append(
                        {
                            'json': {
                                'output': out,
                                'kind': 'transform',
                                'itemIndex': len(out_rows),
                            }
                        }
                    )
                joined_t = (
                    '\n'.join(text_parts)
                    if len(text_parts) > 1
                    else (text_parts[0] if text_parts else '')
                )
                results[nid] = make_wire(out_rows, text=joined_t)
                _log_node(
                    nid,
                    {
                        'nodeId': nid,
                        'nodeType': 'transform',
                        'outputPreview': (joined_t or '')[:500],
                    },
                    t0=_t_node,
                    in_sz=_input_sz,
                )
            elif nt == 'http_request':
                method = str(cfg.get('method') or 'GET').strip().upper()
                if method not in ('GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE'):
                    method = 'GET'
                url_tpl = str(cfg.get('url') or '')
                headers_tpl = str(cfg.get('headersJson') or '{}')
                body_tpl = str(cfg.get('body') or '')
                timeout_s = int(cfg.get('timeoutSeconds') or 30)
                timeout_s = max(1, min(120, timeout_s))
                follow = bool(cfg.get('followRedirects') is True)

                surl = substitute_step_templates(
                    url_tpl,
                    prior_wire_raw=prior_full,
                    prior_text=prior_text,
                    user_input=body.user_input,
                ).strip()
                sh_json = substitute_step_templates(
                    headers_tpl,
                    prior_wire_raw=prior_full,
                    prior_text=prior_text,
                    user_input=body.user_input,
                )
                sbody = substitute_step_templates(
                    body_tpl,
                    prior_wire_raw=prior_full,
                    prior_text=prior_text,
                    user_input=body.user_input,
                )
                w_http = parse_wire(prior_full)
                items_http = w_http.get('items') or []
                all_jsons_http = wire_items_to_json_list(items_http)
                j0h = (
                    (items_http[0].get('json') if items_http and isinstance(items_http[0], dict) else {})
                    or {}
                )
                if not isinstance(j0h, dict):
                    j0h = {}
                ctx_http = ExprContext(json=j0h, item_index=0, input=all_jsons_http)
                surl = substitute_template(surl, ctx_http).strip()
                sh_json = substitute_template(sh_json, ctx_http)
                sbody = substitute_template(sbody, ctx_http)

                if not surl:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail='HTTP Request node: url is empty after substitution',
                    )
                try:
                    validate_public_http_url(surl)
                except ValueError as e:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

                try:
                    hdrs_obj = json.loads(sh_json) if sh_json.strip() else {}
                except json.JSONDecodeError as e:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f'Invalid headers JSON: {e}',
                    ) from e
                if not isinstance(hdrs_obj, dict):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail='headersJson must be a JSON object',
                    )
                hdrs = {str(k): str(v) for k, v in hdrs_obj.items()}

                send_body: Optional[bytes] = None
                if method not in ('GET', 'HEAD') and sbody:
                    send_body = sbody.encode('utf-8')

                try:
                    async with httpx.AsyncClient(timeout=float(timeout_s), follow_redirects=follow) as client:
                        r = await client.request(
                            method,
                            surl,
                            headers=hdrs if hdrs else None,
                            content=send_body,
                        )
                    txt = r.text
                    rh = {k: v for k, v in r.headers.items()}
                    out_w = wrap_http_result(
                        status_code=r.status_code,
                        url=str(r.url),
                        body=txt,
                        response_headers=rh,
                    )
                except httpx.TimeoutException:
                    out_w = wrap_http_result(
                        status_code=None,
                        url=surl,
                        body='',
                        error='Request timed out',
                    )
                except httpx.RequestError as e:
                    out_w = wrap_http_result(
                        status_code=None,
                        url=surl,
                        body='',
                        error=str(e)[:2000],
                    )
                results[nid] = out_w
                _log_node(
                    nid,
                    {
                        'nodeId': nid,
                        'nodeType': 'http_request',
                        'method': method,
                        'requestUrl': surl[:2000],
                        'outputPreview': wire_display_text(parse_wire(out_w))[:500],
                    },
                    t0=_t_node,
                    in_sz=_input_sz,
                )
            elif nt == 'agent':
                outcome = await _execute_agent_step(
                    nid,
                    node,
                    prior_full,
                    parent_id,
                    metrics_t0=_t_node,
                    metrics_input_sz=_input_sz,
                )
                execution_order.append(nid)
                if outcome == 'fatal':
                    return
                await _follow_edges(
                    nid, 'agent', agent_ok=(outcome == 'success')
                )
                return
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f'Unsupported nodeType: {nt}',
                )

            execution_order.append(nid)
            await _follow_edges(nid, nt)
        except ValueError:
            raise
        except HTTPException as e:
            msg = str(e.detail) if e.detail is not None else str(e)
            results[nid] = _workflow_error_wire(nid, msg)
            _fail_run(nid, msg)
            _log_node(
                nid,
                {
                    'nodeId': nid,
                    'nodeType': nt,
                    'error': True,
                    'detail': msg[:2000],
                    'outputPreview': msg[:500],
                },
                t0=_t_node,
                in_sz=_input_sz,
            )
        except Exception as e:
            msg = str(e)[:4000]
            results[nid] = _workflow_error_wire(nid, msg)
            _fail_run(nid, msg)
            _log_node(
                nid,
                {
                    'nodeId': nid,
                    'nodeType': nt,
                    'error': True,
                    'detail': msg,
                    'outputPreview': msg[:500],
                },
                t0=_t_node,
                in_sz=_input_sz,
            )
        finally:
            visit_stack.discard(nid)

    try:
        await dfs_execute(wf.startNodeId)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    final_by_node = {tid: results[tid] for tid in sorted(terminal_ids) if tid in results}
    final_text = _build_final_markdown_from_terminals(
        terminal_ids & set(results.keys()),
        results,
    )

    ok = not run_state['halted']
    items_by_node: dict[str, list[dict[str, Any]]] = {}
    for rnid, w in results.items():
        items_by_node[rnid] = list(parse_wire(w).get('items') or [])
    out: dict[str, Any] = {
        'ok': ok,
        'final': final_text,
        'finalByNode': final_by_node,
        'order': execution_order,
        'results': results,
        'itemsByNode': items_by_node,
        'logs': logs,
    }
    if not ok:
        out['failedNodeId'] = run_state['failed_node_id']
        out['error'] = run_state['failed_error']
        out['partialResults'] = results
    return out
