"""
Workflow integration nodes: Telegram Bot API (sendMessage).

Secrets: prefer env vars (credentialMode=env); inline credentials are stored in workflow JSON — demo only.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from open_webui.workflow_expr import ExprContext, substitute_template, wire_items_to_json_list
from open_webui.workflow_wire import parse_wire, substitute_step_templates, wrap_telegram_result

TELEGRAM_API = 'https://api.telegram.org'


def _resolve_secret(
    cfg: dict[str, Any],
    *,
    inline_key: str,
    env_field: str,
    default_env_name: str,
) -> str:
    mode = str(cfg.get('credentialMode') or 'inline').strip().lower()
    if mode == 'env':
        name = (str(cfg.get(env_field) or '').strip() or default_env_name).strip()
        return (os.environ.get(name) or '').strip()
    return str(cfg.get(inline_key) or '').strip()


def _expr_ctx(prior_full: str, expr_node_map: dict[str, Any]) -> ExprContext:
    w = parse_wire(prior_full)
    items = w.get('items') or []
    all_jsons = wire_items_to_json_list(items)
    j0 = (items[0].get('json') if items and isinstance(items[0], dict) else {}) or {}
    if not isinstance(j0, dict):
        j0 = {}
    return ExprContext(json=j0, item_index=0, input=all_jsons, node=expr_node_map)


async def run_telegram_node(
    cfg: dict[str, Any],
    *,
    prior_full: str,
    prior_text: str,
    user_input: str,
    expr_node_map: dict[str, Any],
) -> str:
    """POST sendMessage to Telegram. Config: botToken/botTokenEnv, chatId, messageText, parseMode, credentialMode."""
    token = _resolve_secret(cfg, inline_key='botToken', env_field='botTokenEnv', default_env_name='TELEGRAM_BOT_TOKEN')
    if not token:
        return wrap_telegram_result(ok=False, error='Telegram: bot token is empty (set inline botToken or env TELEGRAM_BOT_TOKEN).')

    chat_tpl = substitute_step_templates(
        str(cfg.get('chatId') or ''),
        prior_wire_raw=prior_full,
        prior_text=prior_text,
        user_input=user_input,
    )
    msg_tpl = substitute_step_templates(
        str(cfg.get('messageText') or '{{input}}'),
        prior_wire_raw=prior_full,
        prior_text=prior_text,
        user_input=user_input,
    )
    ctx = _expr_ctx(prior_full, expr_node_map)
    chat_id = substitute_template(chat_tpl.strip(), ctx).strip()
    text = substitute_template(msg_tpl, ctx)
    parse_mode = str(cfg.get('parseMode') or '').strip()
    if not chat_id:
        return wrap_telegram_result(ok=False, error='Telegram: chatId is empty after substitution.')
    if not text.strip():
        return wrap_telegram_result(ok=False, error='Telegram: message text is empty after substitution.')

    url = f'{TELEGRAM_API}/bot{token}/sendMessage'
    payload: dict[str, Any] = {'chat_id': chat_id, 'text': text[:4096]}
    if parse_mode in ('HTML', 'Markdown', 'MarkdownV2'):
        payload['parse_mode'] = parse_mode

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(url, json=payload)
            body = r.text
            try:
                data = r.json()
            except Exception:
                data = {'raw': body[:2000]}
            if r.status_code >= 400:
                return wrap_telegram_result(
                    ok=False,
                    error=f'Telegram HTTP {r.status_code}: {body[:2000]}',
                    raw=data if isinstance(data, dict) else None,
                )
            if isinstance(data, dict) and data.get('ok') is True:
                mid = None
                try:
                    mid = int((data.get('result') or {}).get('message_id'))
                except Exception:
                    mid = None
                return wrap_telegram_result(ok=True, message_id=mid, chat_id=chat_id, raw=data)
            err = data.get('description') if isinstance(data, dict) else body
            return wrap_telegram_result(ok=False, error=str(err)[:4000], raw=data if isinstance(data, dict) else None)
    except httpx.RequestError as e:
        return wrap_telegram_result(ok=False, error=f'Telegram request failed: {e!s}'[:4000])
