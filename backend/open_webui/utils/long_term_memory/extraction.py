"""LLM-based memory extraction (JSON). Uses task model via existing chat completion path."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

log = logging.getLogger(__name__)

_EXTRACTION_SYSTEM = """You are a careful memory curator for a personal AI assistant.
Decide if the latest user+assistant exchange contains ONE durable, user-specific fact worth remembering across future chats.

Output ONLY valid JSON with keys:
- "save": boolean
- "category": one of: preference, profile, project, task, constraint, communication_style, habit, ongoing_context, custom
- "content": string, one concise third-person sentence (max 200 chars), or empty if save is false
- "confidence": number 0.0-1.0
- "importance": number 0.0-1.0
- "reason": short string why save or not

Rules:
- Save stable preferences, long-running projects, communication style, recurring goals, important constraints.
- Do NOT save one-off requests, chit-chat, ephemeral info, or anything only useful once.
- Do NOT save secrets, passwords, API keys, payment or government ID data (refuse save=true for those).
- If unsure, set save=false.
"""


def _parse_json_block(raw: str) -> dict[str, Any] | None:
    """Extract a JSON object from LLM output — handles markdown fences, trailing commas, etc."""
    raw = (raw or '').strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)

    m = re.search(r'\{[\s\S]*\}', raw)
    if not m:
        return None

    blob = m.group(0)
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        pass

    blob_clean = re.sub(r',\s*([}\]])', r'\1', blob)
    blob_clean = blob_clean.replace("'", '"')
    try:
        return json.loads(blob_clean)
    except json.JSONDecodeError:
        pass

    for key in ('save', 'content', 'category', 'confidence', 'importance', 'reason'):
        pattern = rf'"{key}"\s*:\s*"([^"]*)"'
        km = re.search(pattern, blob, re.I)
        if km:
            continue
        pattern_unquoted = rf'"{key}"\s*:\s*([^\s,}}]+)'
        km = re.search(pattern_unquoted, blob, re.I)

    save_m = re.search(r'"save"\s*:\s*(true|false)', blob, re.I)
    content_m = re.search(r'"content"\s*:\s*"([^"]*)"', blob)
    if save_m and content_m:
        return {
            'save': save_m.group(1).lower() == 'true',
            'content': content_m.group(1),
            'category': (re.search(r'"category"\s*:\s*"([^"]*)"', blob) or type('', (), {'group': lambda s, i: 'custom'})()).group(1),
            'confidence': float((re.search(r'"confidence"\s*:\s*([\d.]+)', blob) or type('', (), {'group': lambda s, i: '0.6'})()).group(1)),
            'importance': float((re.search(r'"importance"\s*:\s*([\d.]+)', blob) or type('', (), {'group': lambda s, i: '0.5'})()).group(1)),
            'reason': (re.search(r'"reason"\s*:\s*"([^"]*)"', blob) or type('', (), {'group': lambda s, i: ''})()).group(1),
        }
    return None


async def llm_extract_memory_candidate(
    request: Any,
    user: Any,
    *,
    user_message: str,
    assistant_message: str,
    task_model_id: str,
) -> dict[str, Any] | None:
    """Returns validated extraction dict or None on skip/failure."""
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

    umax = int(os.environ.get('LONG_TERM_MEMORY_EXTRACTION_MAX_USER_CHARS', '4000'))
    amax = int(os.environ.get('LONG_TERM_MEMORY_EXTRACTION_MAX_ASSISTANT_CHARS', '8000'))
    u = (user_message or '')[:umax]
    a = (assistant_message or '')[:amax]

    user_block = f'Latest user message:\n{u}\n\nLatest assistant reply:\n{a}'

    payload = {
        'model': task_model_id,
        'messages': [
            {'role': 'system', 'content': _EXTRACTION_SYSTEM},
            {'role': 'user', 'content': user_block},
        ],
        'stream': False,
        'metadata': {
            **(request.state.metadata if hasattr(request.state, 'metadata') else {}),
            'task': 'long_term_memory_extraction',
        },
    }
    mt = models.get(task_model_id) or {}
    if mt.get('owned_by') == 'ollama':
        payload['max_tokens'] = min(600, mt.get('info', {}).get('params', {}).get('max_tokens', 600))
    else:
        payload['max_completion_tokens'] = 600

    try:
        payload = await process_pipeline_inlet_filter(request, payload, user, models)
    except Exception as e:
        log.debug('ltm inlet filter: %s', e)

    try:
        res = await generate_chat_completion(request, form_data=payload, user=user)
    except Exception as e:
        log.warning('ltm extraction LLM failed: %s', e)
        return None

    if not isinstance(res, dict):
        return None

    text = ''
    choices = res.get('choices') or []
    if choices:
        msg = choices[0].get('message') or {}
        text = msg.get('content') or ''
    if not text:
        return None

    data = _parse_json_block(text)
    if not isinstance(data, dict):
        return None
    return data
