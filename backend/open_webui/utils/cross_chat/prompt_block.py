"""Format stored snapshot into a compact prompt block (no raw DB dump)."""

from __future__ import annotations

import os

from open_webui.models.chat_context_snapshots import ChatContextSnapshotModel


def format_snapshot_for_prompt(snap: ChatContextSnapshotModel, max_chars: int | None = None) -> str:
    lim = max_chars or int(os.environ.get('CROSS_CHAT_PROMPT_MAX_CHARS', '4500'))
    parts: list[str] = []
    if (snap.summary or '').strip():
        parts.append(f"Summary: {snap.summary.strip()}")
    kp = snap.key_points or []
    if kp:
        parts.append('Key points:\n' + '\n'.join(f'- {x}' for x in kp[:24]))
    pref = snap.preferences or []
    if pref:
        parts.append('Preferences / style:\n' + '\n'.join(f'- {x}' for x in pref[:16]))
    tasks = snap.ongoing_tasks or []
    if tasks:
        parts.append('Ongoing tasks:\n' + '\n'.join(f'- {x}' for x in tasks[:16]))
    cons = snap.constraints or []
    if cons:
        parts.append('Constraints:\n' + '\n'.join(f'- {x}' for x in cons[:16]))
    text = '\n\n'.join(parts).strip()
    if len(text) > lim:
        text = text[: lim - 3] + '...'
    return text
