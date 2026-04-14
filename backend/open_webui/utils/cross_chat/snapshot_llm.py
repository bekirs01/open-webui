"""LLM-based compact chat snapshot (cross-chat continuity)."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

from open_webui.utils.misc import get_content_from_message, get_message_list

log = logging.getLogger(__name__)

_SYSTEM = """You summarize a conversation for continuing work in a NEW chat later.
Output ONLY valid JSON with keys:
- "summary": string, 2-4 sentences, what this chat was mainly about
- "key_points": array of up to 8 short strings (decisions, facts to remember)
- "preferences": array of up to 6 strings (user style/preferences expressed here)
- "ongoing_tasks": array of up to 6 strings (unfinished work / next steps)
- "constraints": array of up to 6 strings (rules, limits, must-not-forget)

Rules:
- Be compact. No transcript. No message IDs.
- Do NOT include secrets, passwords, API keys, tokens, payment or government ID data.
- If the conversation is too short or empty, still return best-effort empty arrays and a brief summary.
"""


def _parse_json(raw: str) -> dict[str, Any] | None:
    raw = (raw or '').strip()
    m = re.search(r'\{[\s\S]*\}', raw)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _history_to_text(chat: dict, max_chars: int) -> str:
    hist = chat.get('history') or {}
    messages_map = hist.get('messages') or {}
    cur = hist.get('currentId')
    if not messages_map:
        return ''
    if cur:
        chain = get_message_list(messages_map, cur)
    else:
        chain = list(messages_map.values())
    lines: list[str] = []
    for msg in chain:
        if not isinstance(msg, dict) or not msg.get('role'):
            continue
        role = msg['role']
        if role not in ('user', 'assistant', 'system'):
            continue
        content = get_content_from_message(msg) or ''
        content = (content or '').strip()
        if len(content) > 8000:
            content = content[:8000] + '...'
        if content:
            lines.append(f'{role.upper()}: {content}')
    text = '\n\n'.join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + '\n... [truncated]'
    return text


def _sanitize_lists(obj: dict[str, Any]) -> dict[str, Any]:
    from open_webui.utils.long_term_memory.safety import is_likely_sensitive

    def clean_arr(key: str, max_n: int) -> list[str]:
        raw = obj.get(key) or []
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        for x in raw[:max_n]:
            if not isinstance(x, str):
                continue
            s = x.strip()
            if not s or len(s) > 400:
                continue
            if is_likely_sensitive(s):
                continue
            out.append(s)
        return out

    summary = obj.get('summary') or ''
    if not isinstance(summary, str):
        summary = ''
    summary = summary.strip()
    if is_likely_sensitive(summary):
        summary = '[redacted: sensitive pattern]'
    if len(summary) > 2000:
        summary = summary[:2000] + '...'

    return {
        'summary': summary,
        'key_points': clean_arr('key_points', 8),
        'preferences': clean_arr('preferences', 6),
        'ongoing_tasks': clean_arr('ongoing_tasks', 6),
        'constraints': clean_arr('constraints', 6),
    }


async def llm_build_snapshot(
    request: Any,
    user: Any,
    chat_payload: dict,
    *,
    task_model_id: str,
) -> Optional[dict[str, Any]]:
    from open_webui.routers.pipelines import process_pipeline_inlet_filter
    from open_webui.utils.chat import generate_chat_completion
    from open_webui.utils.task import get_task_model_id

    models = request.app.state.MODELS
    if task_model_id not in models:
        task_model_id = get_task_model_id(
            task_model_id,
            request.app.state.config.TASK_MODEL,
            request.app.state.config.TASK_MODEL_EXTERNAL,
            models,
        )

    max_hist = int(os.environ.get('CROSS_CHAT_SNAPSHOT_MAX_HISTORY_CHARS', '14000'))
    block = _history_to_text(chat_payload, max_hist)
    if not block.strip():
        return {
            'summary': 'Empty conversation.',
            'key_points': [],
            'preferences': [],
            'ongoing_tasks': [],
            'constraints': [],
        }

    payload = {
        'model': task_model_id,
        'messages': [
            {'role': 'system', 'content': _SYSTEM},
            {'role': 'user', 'content': f'Conversation transcript (may be truncated):\n\n{block}'},
        ],
        'stream': False,
        'metadata': {
            **(request.state.metadata if hasattr(request.state, 'metadata') else {}),
            'task': 'cross_chat_snapshot',
        },
    }
    mt = models.get(task_model_id) or {}
    if mt.get('owned_by') == 'ollama':
        payload['max_tokens'] = min(900, mt.get('info', {}).get('params', {}).get('max_tokens', 900))
    else:
        payload['max_completion_tokens'] = 900

    try:
        payload = await process_pipeline_inlet_filter(request, payload, user, models)
    except Exception as e:
        log.debug('cross_chat inlet filter: %s', e)

    try:
        res = await generate_chat_completion(request, form_data=payload, user=user)
    except Exception as e:
        log.warning('cross_chat snapshot LLM failed: %s', e)
        return None

    try:
        raw = res['choices'][0]['message']['content']
    except Exception:
        return None

    data = _parse_json(raw)
    if not data:
        return None
    return _sanitize_lists(data)
