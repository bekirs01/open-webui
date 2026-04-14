"""
n8n-style wire payload between workflow nodes: JSON envelope with items[].json.

Schema:
  { "$wf": 1, "items": [ { "json": { ... } } ], "text": "<human-readable for LLM>" }
"""

from __future__ import annotations

import json
from typing import Any, Optional

WIRE_VERSION = 1


def parse_wire(raw: str) -> dict[str, Any]:
    """Parse step output string into a wire dict (always has $wf, items, text)."""
    s = (raw or '').strip()
    if not s:
        return _empty_wire()

    try:
        obj = json.loads(s)
    except Exception:
        return _legacy_plain_text(s)

    if isinstance(obj, dict) and obj.get('$wf') == WIRE_VERSION and isinstance(obj.get('items'), list):
        return _normalize_wire_obj(obj)

    # Legacy structured JSON (image_result, if_result, agent_error, plain dict from LLM)
    return _legacy_object_to_wire(obj, original_string=s)


def _empty_wire() -> dict[str, Any]:
    return {'$wf': WIRE_VERSION, 'items': [], 'text': ''}


def _legacy_plain_text(s: str) -> dict[str, Any]:
    return {
        '$wf': WIRE_VERSION,
        'items': [{'json': {'_legacyText': s}}],
        'text': s,
    }


def _legacy_object_to_wire(obj: dict[str, Any], *, original_string: str) -> dict[str, Any]:
    kind = obj.get('type')
    if kind == 'image_result':
        return {
            '$wf': WIRE_VERSION,
            'items': [{'json': dict(obj)}],
            'text': (obj.get('prompt') or '') or original_string,
        }
    if kind == 'if_result':
        br = bool(obj.get('branch'))
        return {
            '$wf': WIRE_VERSION,
            'items': [{'json': {'type': 'if_result', 'branch': br}}],
            'text': 'true' if br else 'false',
        }
    if kind == 'agent_error':
        return {
            '$wf': WIRE_VERSION,
            'items': [{'json': dict(obj)}],
            'text': str(obj.get('detail') or '')[:4000],
        }
    if kind == 'workflow_error':
        return {
            '$wf': WIRE_VERSION,
            'items': [{'json': dict(obj)}],
            'text': str(obj.get('message') or '')[:12000],
        }
    if kind == 'http_result':
        body = obj.get('body')
        tx = body if isinstance(body, str) else ''
        if not tx.strip() and isinstance(obj.get('error'), str):
            tx = str(obj.get('error') or '')
        return {
            '$wf': WIRE_VERSION,
            'items': [{'json': dict(obj)}],
            'text': (tx or str(obj.get('statusCode') or ''))[:12000],
        }
    # Bare JSON object from older agent (no envelope)
    return {
        '$wf': WIRE_VERSION,
        'items': [{'json': dict(obj)}],
        'text': json.dumps(obj, ensure_ascii=False)[:12000],
    }


def _normalize_wire_obj(obj: dict[str, Any]) -> dict[str, Any]:
    items = obj.get('items') or []
    if not isinstance(items, list):
        items = []
    norm_items: list[dict[str, Any]] = []
    for it in items:
        if isinstance(it, dict) and isinstance(it.get('json'), dict):
            norm_items.append({'json': it['json']})
        elif isinstance(it, dict):
            norm_items.append({'json': dict(it)})
    text = obj.get('text')
    if not isinstance(text, str):
        text = ''
    return {'$wf': WIRE_VERSION, 'items': norm_items, 'text': text}


def make_wire(items: list[dict[str, Any]], *, text: Optional[str] = None) -> str:
    """Serialize wire. Each item must be { 'json': { ... } } or we wrap as json."""
    norm: list[dict[str, Any]] = []
    for it in items:
        if isinstance(it, dict) and 'json' in it and isinstance(it['json'], dict):
            norm.append({'json': it['json']})
        elif isinstance(it, dict):
            norm.append({'json': dict(it)})
    if text is None:
        text = ''
        if norm:
            try:
                text = json.dumps(norm[0]['json'], ensure_ascii=False)[:12000]
            except Exception:
                text = ''
    payload = {'$wf': WIRE_VERSION, 'items': norm, 'text': text}
    return json.dumps(payload, ensure_ascii=False)


def wire_display_text(wire: dict[str, Any]) -> str:
    """Short text for substring IF / previews."""
    t = wire.get('text')
    if isinstance(t, str) and t.strip():
        return t
    items = wire.get('items') or []
    if items and isinstance(items[0], dict):
        j = items[0].get('json')
        if isinstance(j, dict):
            if j.get('type') == 'image_result':
                return (j.get('prompt') or '') or ''
            if j.get('type') == 'if_result':
                return 'true' if j.get('branch') else 'false'
            if j.get('type') == 'http_result':
                b = j.get('body')
                if isinstance(b, str) and b.strip():
                    return b[:8000]
                err = j.get('error')
                if isinstance(err, str) and err.strip():
                    return err[:8000]
                sc = j.get('statusCode')
                return str(sc) if sc is not None else ''
            if j.get('type') == 'telegram_result':
                if not j.get('ok') and isinstance(j.get('error'), str):
                    return str(j.get('error') or '')[:8000]
                return f"telegram ok message_id={j.get('messageId')}"[:8000]
            if j.get('type') == 'workflow_error':
                return str(j.get('message') or '')[:8000]
            try:
                return json.dumps(j, ensure_ascii=False)[:8000]
            except Exception:
                return ''
    return ''


def wire_for_llm_context(raw: str) -> str:
    """Full wire JSON (compact) for agent/transform previous-step field."""
    w = parse_wire(raw)
    try:
        return json.dumps(w, ensure_ascii=False, indent=2)[:24000]
    except Exception:
        return wire_display_text(w)


def get_by_path(root: Any, path: str) -> Any:
    """Dot path: items.0.json.status — numeric parts index into lists."""
    if not path or not isinstance(path, str):
        return root
    cur: Any = root
    for part in path.split('.'):
        if part == '':
            continue
        if cur is None:
            return None
        if isinstance(cur, list):
            try:
                idx = int(part)
            except ValueError:
                return None
            if idx < 0 or idx >= len(cur):
                return None
            cur = cur[idx]
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _coerce_num(x: Any) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, bool):
        return float(x)
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x).strip().replace(',', '.'))
    except Exception:
        return None


def eval_if_json_compare(
    prior_raw: str,
    *,
    json_path: str,
    operator: str,
    compare_value: str,
) -> bool:
    wire = parse_wire(prior_raw)
    op = (operator or 'equals').strip().lower()
    if op == 'isnotempty':
        op = 'exists'
    if op == 'isempty':
        op = 'notexists'
    path = (json_path or '').strip()
    want = compare_value
    got = get_by_path(wire, path)

    if op in ('exists', 'isnotempty'):
        if got is None:
            return False
        if isinstance(got, str):
            return bool(got.strip())
        if isinstance(got, (list, dict)):
            return len(got) > 0
        return True

    if op in ('notexists', 'isempty'):
        if got is None:
            return True
        if isinstance(got, str):
            return not got.strip()
        if isinstance(got, (list, dict)):
            return len(got) == 0
        return False

    gs = '' if got is None else (json.dumps(got, ensure_ascii=False) if not isinstance(got, str) else got)
    ws = want.strip()

    if op == 'equals':
        return gs.strip() == ws
    if op == 'notequals':
        return gs.strip() != ws
    if op == 'contains':
        return ws.lower() in gs.lower()
    if op == 'notcontains':
        return ws.lower() not in gs.lower()

    a = _coerce_num(got)
    b = _coerce_num(want)
    if a is None or b is None:
        return False
    if op == 'gt':
        return a > b
    if op == 'gte':
        return a >= b
    if op == 'lt':
        return a < b
    if op == 'lte':
        return a <= b

    return False


def wrap_agent_text_reply(llm_text: str) -> str:
    """Agent text output -> wire; if reply is JSON object, use as items[0].json."""
    t = (llm_text or '').strip()
    if not t:
        return make_wire([{'json': {'reply': ''}}], text='')

    try:
        parsed = json.loads(t)
        if isinstance(parsed, dict):
            return make_wire([{'json': parsed}], text=t[:12000])
    except Exception:
        pass
    return make_wire([{'json': {'reply': t}}], text=t[:12000])


def wrap_trigger(user_input: str) -> str:
    ui = (user_input or '').strip()
    # `status` mirrors user input so paths like items.0.json.status match n8n-style examples.
    return make_wire(
        [{'json': {'userInput': ui, 'kind': 'trigger', 'status': ui}}],
        text=ui,
    )


def wrap_transform_output(out: str) -> str:
    o = out or ''
    return make_wire([{'json': {'output': o, 'kind': 'transform'}}], text=o)


def wrap_if_result(branch: bool) -> str:
    return make_wire(
        [{'json': {'type': 'if_result', 'branch': branch}}],
        text='true' if branch else 'false',
    )


def substitute_step_templates(
    template: str,
    *,
    prior_wire_raw: str,
    prior_text: str,
    user_input: str,
) -> str:
    """Same placeholders as Transform: {{input}}, {{json}}, {{user_input}}."""
    w = parse_wire(prior_wire_raw)
    items = w.get('items') or []
    item0 = items[0] if items else {}
    j0 = item0.get('json') if isinstance(item0, dict) else {}
    if not isinstance(j0, dict):
        j0 = {}
    json_snip = json.dumps(j0, ensure_ascii=False)
    pt = prior_text or ''
    ui = (user_input or '').strip()
    t = template if template is not None else ''
    return (
        t.replace('{{input}}', pt)
        .replace('{{INPUT}}', pt)
        .replace('{{json}}', json_snip)
        .replace('{{JSON}}', json_snip)
        .replace('{{user_input}}', ui)
        .replace('{{USER_INPUT}}', ui)
    )


def wrap_http_result(
    *,
    status_code: Optional[int],
    url: str,
    body: str,
    response_headers: Optional[dict[str, str]] = None,
    error: Optional[str] = None,
) -> str:
    """HTTP Request node output as wire (items[0].json.type == http_result)."""
    obj: dict[str, Any] = {
        'type': 'http_result',
        'url': (url or '')[:4000],
        'body': (body or '')[:48000],
    }
    if status_code is not None:
        obj['statusCode'] = int(status_code)
    if error:
        obj['error'] = (error or '')[:4000]
    if response_headers:
        obj['responseHeaders'] = {
            str(k)[:256]: str(v)[:2000] for k, v in list(response_headers.items())[:64]
        }
    preview = (body or '')[:12000] if body else (error or '')[:12000]
    return make_wire([{'json': obj}], text=preview or str(status_code or ''))


def wrap_telegram_result(
    *,
    ok: bool,
    error: Optional[str] = None,
    message_id: Optional[int] = None,
    chat_id: Optional[str] = None,
    raw: Optional[dict[str, Any]] = None,
) -> str:
    """Telegram sendMessage node output (items[0].json.type == telegram_result)."""
    obj: dict[str, Any] = {'type': 'telegram_result', 'ok': bool(ok)}
    if error:
        obj['error'] = (error or '')[:4000]
    if message_id is not None:
        obj['messageId'] = int(message_id)
    if chat_id is not None:
        obj['chatId'] = str(chat_id)[:128]
    if raw is not None and isinstance(raw, dict):
        obj['response'] = raw
    preview = (error or '')[:12000] if not ok else f'message_id={message_id}' if message_id is not None else 'ok'
    return make_wire([{'json': obj}], text=preview[:12000])


def branch_from_if_output(result_str: str) -> bool:
    """Read boolean branch from IF node output (wire or legacy)."""
    w = parse_wire(result_str)
    items = w.get('items') or []
    if items and isinstance(items[0], dict):
        j = items[0].get('json') or {}
        if isinstance(j, dict) and j.get('type') == 'if_result':
            return bool(j.get('branch'))
    try:
        obj = json.loads(result_str)
        if isinstance(obj, dict) and obj.get('type') == 'if_result':
            return bool(obj.get('branch'))
    except Exception:
        pass
    return False
