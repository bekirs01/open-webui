"""Post-turn memory extraction scheduling and persistence."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Tuple

log = logging.getLogger(__name__)

_VALID_CATEGORIES = frozenset(
    {
        'preference',
        'profile',
        'project',
        'task',
        'constraint',
        'communication_style',
        'habit',
        'ongoing_context',
        'lesson',
        'entity',
        'custom',
    }
)


def _text_from_content(content: Any) -> str:
    """Extract plain text from a message content field (str or list-of-parts)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict) and p.get('type') == 'text':
                parts.append(p.get('text') or '')
        return '\n'.join(parts)
    return ''


def _extract_user_assistant_pairs(
    messages: list[dict],
    *,
    max_pairs: int | None = None,
) -> list[tuple[str, str]]:
    """Return (user_text, assistant_text) pairs from message list, newest first.

    When *max_pairs* is None the env ``LONG_TERM_MEMORY_BATCH_PAIRS`` controls
    how many pairs to extract (default 3 — covers the last few turns so longer
    conversations also get their earlier facts captured).
    """
    if max_pairs is None:
        max_pairs = int(os.environ.get('LONG_TERM_MEMORY_BATCH_PAIRS', '3'))
    max_pairs = max(1, min(max_pairs, 10))

    pairs: list[tuple[str, str]] = []
    last_asst = ''
    for m in reversed(messages):
        role = m.get('role')
        if role == 'assistant' and not last_asst:
            last_asst = _text_from_content(m.get('content'))
        elif role == 'user' and last_asst:
            ut = _text_from_content(m.get('content'))
            if len(ut.strip()) >= 8 and len(last_asst.strip()) >= 4:
                pairs.append((ut, last_asst))
            last_asst = ''
            if len(pairs) >= max_pairs:
                break
    return pairs


def _user_allows_auto_extract(user_settings: dict | None) -> bool:
    if not user_settings:
        return True
    if 'memory_auto_extract' in user_settings:
        return bool(user_settings.get('memory_auto_extract'))
    ui = user_settings.get('ui') or {}
    if isinstance(ui, dict) and 'memory_auto_extract' in ui:
        return bool(ui.get('memory_auto_extract'))
    return True


def _filter_memories_for_dedupe_scope(
    rows: list[dict], folder_id: str | None, apply_scope: bool
) -> list[dict]:
    """Dedupe only against memories visible in the same folder scope as the current chat."""
    if not apply_scope:
        return rows
    out: list[dict] = []
    for r in rows:
        fid = r.get('folder_id')
        if folder_id is None:
            if fid is None:
                out.append(r)
        else:
            if fid is None or fid == folder_id:
                out.append(r)
    return out


def schedule_memory_extraction(request: Any, result: dict, user: Any) -> None:
    """Fire-and-forget: run after chat outlet; must not raise."""
    if os.environ.get('LONG_TERM_MEMORY_AUTO_EXTRACT', 'true').lower() != 'true':
        return
    try:
        if not request.app.state.config.ENABLE_MEMORIES:
            return
    except Exception:
        return

    try:
        asyncio.create_task(_run_extraction_safe(request, result, user))
    except RuntimeError:
        asyncio.run(_run_extraction_safe(request, result, user))


async def _run_extraction_safe(request: Any, result: dict, user: Any) -> None:
    try:
        await run_memory_extraction(request, result, user)
    except Exception as e:
        log.debug('long-term memory extraction skipped: %s', e)


async def run_memory_extraction(request: Any, result: dict, user: Any) -> None:
    from open_webui.models.users import Users
    from open_webui.utils.access_control import has_permission

    if not has_permission(user.id, 'features.memories', request.app.state.config.USER_PERMISSIONS):
        return

    udb = Users.get_user_by_id(user.id)
    settings = udb.settings if udb and udb.settings else {}
    if hasattr(settings, 'model_dump'):
        settings = settings.model_dump()
    if not isinstance(settings, dict):
        settings = {}
    if not _user_allows_auto_extract(settings):
        return

    messages = result.get('messages') or []
    if not messages:
        return

    pairs = _extract_user_assistant_pairs(messages)
    if not pairs:
        return

    from open_webui.utils.long_term_memory.extraction import llm_extract_memory_candidate
    from open_webui.utils.long_term_memory.safety import is_likely_sensitive, normalize_for_dedupe
    from open_webui.utils.long_term_memory.dedupe import best_fuzzy_match
    from open_webui.models.chats import Chats
    from open_webui.models.memories import Memories
    from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT

    models = request.app.state.MODELS
    default_id = next(iter(models.keys())) if models else ''
    task_model = os.environ.get('LONG_TERM_MEMORY_TASK_MODEL') or request.app.state.config.TASK_MODEL or default_id
    chat_id = result.get('chat_id')
    apply_fs = os.environ.get('FOLDER_SHARED_MEMORY', 'true').lower() == 'true'
    folder_id: str | None = None
    if apply_fs and chat_id and user:
        folder_id = Chats.get_chat_folder_id(chat_id, user.id)

    existing = Memories.get_memories_by_user_id(user.id, status='active')
    ex_rows = _filter_memories_for_dedupe_scope(
        [m.model_dump() for m in existing], folder_id, apply_fs
    )
    dedupe_threshold = float(os.environ.get('LONG_TERM_MEMORY_DEDUPE_THRESHOLD', '0.88'))
    min_conf = float(os.environ.get('LONG_TERM_MEMORY_MIN_CONFIDENCE', '0.45'))

    for last_user, last_asst in pairs:
        await _process_single_pair(
            request,
            user,
            last_user,
            last_asst,
            task_model_id=task_model,
            chat_id=chat_id,
            existing_rows=ex_rows,
            dedupe_threshold=dedupe_threshold,
            min_confidence=min_conf,
            folder_id=folder_id,
            apply_folder_scope=apply_fs,
        )

    _maybe_archive_stale(user.id)


def _find_supersede_target(
    supersedes_hint: str | None,
    existing_rows: list[dict],
    threshold: float = 0.55,
) -> dict[str, Any] | None:
    """Find an existing memory that the new fact supersedes based on the LLM hint."""
    if not supersedes_hint or not existing_rows:
        return None
    import difflib
    from open_webui.utils.long_term_memory.safety import normalize_for_dedupe
    hint_norm = normalize_for_dedupe(supersedes_hint)
    if len(hint_norm) < 5:
        return None

    best: Tuple[float, dict[str, Any]] | None = None
    for row in existing_rows:
        content = row.get('normalized_content') or row.get('content') or ''
        if not content:
            continue
        n = normalize_for_dedupe(str(content))
        ratio = difflib.SequenceMatcher(a=hint_norm, b=n).ratio()
        if best is None or ratio > best[0]:
            best = (ratio, row)
    if best and best[0] >= threshold:
        return best[1]
    return None


async def _persist_memory(
    request: Any,
    user: Any,
    content: str,
    norm: str,
    *,
    cat: str,
    conf: float,
    imp: float,
    excerpt: str,
    chat_id: str | None,
    mem_folder: str | None,
    reason: str,
    existing_rows: list[dict],
    dedupe_threshold: float,
    supersedes_hint: str | None,
) -> None:
    """Validate, dedup/supersede, and persist a single extracted memory."""
    from open_webui.utils.long_term_memory.dedupe import best_fuzzy_match
    from open_webui.models.memories import Memories
    from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT

    dup = best_fuzzy_match(norm, existing_rows, threshold=dedupe_threshold)

    supersede_target = None
    if not dup and supersedes_hint:
        supersede_target = _find_supersede_target(supersedes_hint, existing_rows)

    update_target = dup or supersede_target

    if update_target:
        if supersede_target and not dup:
            new_conf = conf
            new_imp = imp
            extra = {
                'reason': reason,
                'superseded_from': supersede_target.get('content', ''),
            }
        else:
            new_conf = min(1.0, float(update_target.get('confidence_score') or 0.5) + 0.08)
            new_imp = min(1.0, max(float(update_target.get('importance_score') or 0.4), imp))
            extra = None

        update_kwargs: dict[str, Any] = dict(
            normalized_content=norm,
            confidence_score=new_conf,
            importance_score=new_imp,
            source_excerpt=excerpt,
            chat_id=chat_id,
            category=cat,
            source_type='chat_auto',
            folder_id=mem_folder,
        )
        if extra:
            update_kwargs['ltm_extra'] = extra

        Memories.update_memory_by_id_and_user_id(
            update_target['id'], user.id, content, **update_kwargs,
        )
        mem = Memories.get_memory_by_id(update_target['id'])
        if mem:
            vector = await request.app.state.EMBEDDING_FUNCTION(mem.content, user=user)
            VECTOR_DB_CLIENT.upsert(
                collection_name=f'user-memory-{user.id}',
                items=[{
                    'id': mem.id,
                    'text': mem.content,
                    'vector': vector,
                    'metadata': {
                        'created_at': mem.created_at,
                        'updated_at': int(time.time()),
                        'status': mem.status or 'active',
                        'category': mem.category or 'custom',
                        'importance': float(mem.importance_score or 0),
                        'confidence': float(mem.confidence_score or 0),
                        'folder_id': (mem.folder_id or ''),
                    },
                }],
            )
        return

    mem = Memories.insert_new_memory(
        user.id,
        content,
        chat_id=chat_id,
        category=cat,
        normalized_content=norm,
        source_excerpt=excerpt,
        confidence_score=conf,
        importance_score=imp,
        source_type='chat_auto',
        status='active',
        ltm_extra={'reason': reason},
        folder_id=mem_folder,
    )
    if not mem:
        return

    vector = await request.app.state.EMBEDDING_FUNCTION(mem.content, user=user)
    VECTOR_DB_CLIENT.upsert(
        collection_name=f'user-memory-{user.id}',
        items=[{
            'id': mem.id,
            'text': mem.content,
            'vector': vector,
            'metadata': {
                'created_at': mem.created_at,
                'updated_at': mem.updated_at,
                'status': 'active',
                'category': cat,
                'importance': imp,
                'confidence': conf,
                'folder_id': (mem.folder_id or ''),
            },
        }],
    )


async def _process_single_pair(
    request: Any,
    user: Any,
    last_user: str,
    last_asst: str,
    *,
    task_model_id: str,
    chat_id: str | None,
    existing_rows: list[dict],
    dedupe_threshold: float,
    min_confidence: float,
    folder_id: str | None,
    apply_folder_scope: bool,
) -> None:
    """Extract, validate, dedup, and persist a single user+assistant pair."""
    from open_webui.utils.long_term_memory.extraction import llm_extract_memory_candidate
    from open_webui.utils.long_term_memory.safety import is_likely_sensitive, normalize_for_dedupe

    candidates = await llm_extract_memory_candidate(
        request,
        user,
        user_message=last_user,
        assistant_message=last_asst,
        task_model_id=task_model_id,
    )
    if not candidates:
        return

    excerpt = (last_user[:200] + ' -> ' + last_asst[:200])[:400]
    mem_folder = folder_id if apply_folder_scope else None

    for raw in candidates:
        if not raw.get('save'):
            continue

        content = (raw.get('content') or '').strip()
        if len(content) < 10:
            continue

        if is_likely_sensitive(content) or is_likely_sensitive(last_user) or is_likely_sensitive(last_asst):
            log.debug('ltm: rejected sensitive')
            continue

        cat = (raw.get('category') or 'custom').strip().lower()
        if cat not in _VALID_CATEGORIES:
            cat = 'custom'

        try:
            conf = float(raw.get('confidence') or 0.6)
            imp = float(raw.get('importance') or 0.5)
        except (TypeError, ValueError):
            conf, imp = 0.6, 0.5
        conf = max(0.0, min(1.0, conf))
        imp = max(0.0, min(1.0, imp))

        if conf < min_confidence:
            continue

        norm = normalize_for_dedupe(content)

        await _persist_memory(
            request, user, content, norm,
            cat=cat, conf=conf, imp=imp,
            excerpt=excerpt, chat_id=chat_id,
            mem_folder=mem_folder,
            reason=raw.get('reason', ''),
            existing_rows=existing_rows,
            dedupe_threshold=dedupe_threshold,
            supersedes_hint=raw.get('supersedes'),
        )


_STALE_ARCHIVE_COUNTER: dict[str, int] = {}
_STALE_ARCHIVE_INTERVAL = 20


def _maybe_archive_stale(user_id: str) -> None:
    """Run stale cleanup periodically (every N extraction runs per user)."""
    _STALE_ARCHIVE_COUNTER[user_id] = _STALE_ARCHIVE_COUNTER.get(user_id, 0) + 1
    if _STALE_ARCHIVE_COUNTER[user_id] % _STALE_ARCHIVE_INTERVAL != 0:
        return
    try:
        from open_webui.models.memories import Memories
        stale_days = int(os.environ.get('LTM_STALE_ARCHIVE_DAYS', '90'))
        min_access = int(os.environ.get('LTM_STALE_MIN_ACCESS', '1'))
        min_imp = float(os.environ.get('LTM_STALE_MIN_IMPORTANCE', '0.3'))
        n = Memories.archive_stale_memories(
            user_id, stale_days=stale_days,
            min_access_count=min_access, min_importance=min_imp,
        )
        if n:
            log.info('ltm: archived %d stale memories for user %s', n, user_id[:8])
    except Exception as e:
        log.debug('ltm stale cleanup: %s', e)
