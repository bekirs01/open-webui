"""Conversation summaries from sibling chats in the same folder (shared context)."""

from __future__ import annotations

import os


def build_folder_peer_context(
    *,
    user_id: str,
    current_chat_id: str,
    folder_id: str,
    max_bytes_override: int | None = None,
    max_siblings_override: int | None = None,
    max_turns_override: int | None = None,
) -> str:
    from open_webui.models.chats import Chats
    from open_webui.utils.misc import get_content_from_message, get_message_list

    max_bytes = max_bytes_override or int(os.environ.get('FOLDER_PEER_CONTEXT_MAX_BYTES', '16000'))
    max_bytes = max(500, min(max_bytes, 64000))
    max_siblings = max_siblings_override or int(os.environ.get('FOLDER_PEER_MAX_SIBLINGS', '15'))
    max_siblings = max(1, min(max_siblings, 30))
    max_turns_per_chat = max_turns_override or int(os.environ.get('FOLDER_PEER_MAX_TURNS', '8'))
    max_turns_per_chat = max(2, min(max_turns_per_chat, 20))

    rows = Chats.get_chats_by_folder_id_and_user_id(folder_id, user_id, skip=0, limit=80)
    siblings = [c for c in rows if c.id != current_chat_id]

    parts: list[str] = []
    total = 0

    for c in siblings:
        if len(parts) >= max_siblings:
            break
        hist = (c.chat or {}).get('history') or {}
        mm = hist.get('messages') or {}
        cid = hist.get('currentId')
        if not isinstance(mm, dict) or not cid:
            continue
        chain = get_message_list(mm, cid)

        turn_lines: list[str] = []
        collected = 0
        for msg in reversed(chain):
            if collected >= max_turns_per_chat:
                break
            role = msg.get('role', '')
            if role not in ('user', 'assistant'):
                continue
            t = (get_content_from_message(msg) or '').strip()
            if len(t) < 8:
                continue
            label = 'User' if role == 'user' else 'Assistant'
            turn_lines.append(f"  [{label}]: {t[:2000]}")
            collected += 1

        if not turn_lines:
            continue

        turn_lines.reverse()
        title = ((c.title or '') or 'Chat').strip()[:120]
        block = f"### {title}\n" + '\n'.join(turn_lines)
        if total + len(block) + 4 > max_bytes:
            break
        parts.append(block)
        total += len(block) + 4

    if not parts:
        return ''

    head = (
        'This folder contains related chats. Below are recent conversations from sibling '
        'chats in the same folder. You have full access to what was discussed in ALL of '
        'these chats. Use this information to answer follow-up questions, recall facts, '
        'names, preferences, and decisions shared across chats. Treat ALL of this as '
        'your own continuous memory.\n\n'
    )
    return head + '\n\n'.join(parts)
