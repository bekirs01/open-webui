"""
Compact, idempotent system hints for routing (knowledge vs memory vs tools) and prompt adherence.
Injected for all chat completions (not only MWS-tagged models).
"""

from __future__ import annotations

import os

CHAT_ROUTE_HINT_MARKER = '[CHAT_ROUTE_AND_ADHERENCE_v1]'


def _hint_enabled() -> bool:
    return (os.environ.get('CHAT_ROUTE_HINT_ENABLED', 'true') or 'true').lower() == 'true'


def _messages_contain_marker(messages: list[dict] | None, marker: str) -> bool:
    for m in messages or []:
        if m.get('role') != 'system':
            continue
        c = m.get('content')
        if isinstance(c, str) and marker in c:
            return True
        if isinstance(c, list):
            blob = ''.join(
                (p.get('text') or '') for p in c if isinstance(p, dict) and p.get('type') in ('text', 'input_text')
            )
            if marker in blob:
                return True
    return False


def build_chat_route_and_adherence_hint() -> str:
    return (
        f'{CHAT_ROUTE_HINT_MARKER}\n'
        '### Assistant routing and prompt discipline (mandatory)\n'
        '- **System prompts are binding:** Obey the model’s configured system prompt, any workspace/folder system prompt, '
        'and higher-priority safety rules. Do not contradict them unless the user explicitly overrides a non-safety '
        'constraint.\n'
        '- **Direct chat:** For greetings, thanks, or short general chat with no document or workspace context, answer '
        'directly. Do not invent that you searched a knowledge base when retrieval did not run.\n'
        '- **Knowledge / RAG:** When the user asks about attached files, knowledge collections, project/workspace docs, or '
        'policies, ground factual claims in retrieved context. If the provided context does not contain the answer, say '
        'so clearly in the user’s language—do not fabricate document content.\n'
        '- **Memory:** When the user asks about what they said before, prior preferences, or “do you remember…”, rely on '
        'User Memories (or memory tools) before unrelated knowledge-base snippets.\n'
        '- **Tools:** When tools are enabled and they are the right way to get an accurate result (execution, live data, '
        'file operations), use them instead of guessing.\n'
        '- **One reply language:** Use exactly **one** language for the whole answer—the same as the user’s latest message. '
        'Do not mix English, French, Chinese, or other languages in a single reply; translate foreign snippets into that language.\n'
        '- **Answer depth:** Give a **full, helpful** response (enough sentences and structure to solve the user’s request). '
        'Avoid trivial two-word answers unless the user clearly asked for the shortest possible reply.\n'
    )


def inject_chat_route_and_adherence_hint(messages: list[dict] | None) -> list[dict]:
    from open_webui.utils.misc import add_or_update_system_message

    if not messages or not _hint_enabled():
        return messages or []
    if _messages_contain_marker(messages, CHAT_ROUTE_HINT_MARKER):
        return messages
    return add_or_update_system_message(build_chat_route_and_adherence_hint(), messages, append=True)
