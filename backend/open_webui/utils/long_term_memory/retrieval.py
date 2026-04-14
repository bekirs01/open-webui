"""Rank vector hits using DB scores + usage + time-decay."""

from __future__ import annotations

import logging
import math
import os
import time
from typing import Any

from open_webui.models.memories import Memories, MemoryModel

log = logging.getLogger(__name__)

# ChromaDB returns *cosine distance* (0 = identical, 2 = opposite).
# Many other backends (Qdrant with cosine, Milvus) return *similarity* (1 = identical).
# We normalize: higher = more similar.
_VECTOR_SCORE_IS_DISTANCE = os.environ.get('LTM_VECTOR_SCORE_IS_DISTANCE', 'true').lower() == 'true'

# Exponential half-life for recency decay (days). Memories older than this lose
# half their recency weight. Lower = more aggressive forgetting of old items.
_RECENCY_HALF_LIFE_DAYS = float(os.environ.get('LTM_RECENCY_HALF_LIFE_DAYS', '60'))


def _normalize_vector_score(raw: float) -> float:
    """Convert raw vector score to a 0-1 similarity value."""
    if _VECTOR_SCORE_IS_DISTANCE:
        return max(0.0, min(1.0, 1.0 - raw / 2.0))
    return max(0.0, min(1.0, raw))


def _time_decay(age_days: float) -> float:
    """Exponential decay: returns 1.0 for fresh items, halves every _RECENCY_HALF_LIFE_DAYS."""
    hl = max(1.0, _RECENCY_HALF_LIFE_DAYS)
    return math.exp(-0.693147 * age_days / hl)


def memory_visible_in_folder_scope(m: MemoryModel, folder_scope_id: str | None) -> bool:
    """When folder_scope_id is set: include global (no folder) + that folder. Else: global only."""
    fid = getattr(m, 'folder_id', None) or None
    if folder_scope_id is None:
        return fid is None
    return fid is None or fid == folder_scope_id


async def fetch_ranked_memories(
    request: Any,
    user: Any,
    query_text: str,
    top_k: int,
    *,
    folder_scope_id: str | None = None,
    apply_folder_scope: bool = True,
) -> list[MemoryModel]:
    """Embed query, vector search, then rank by importance/confidence/recency."""
    from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT

    if not (query_text or '').strip():
        return []

    memories = Memories.get_memories_by_user_id(user.id, status='active')
    if not memories:
        return []

    try:
        vector = await request.app.state.EMBEDDING_FUNCTION(query_text, user=user)
    except Exception as e:
        log.debug('ltm retrieval embed failed: %s', e)
        return []

    lim = min(max(top_k * 4, 12), 64)
    results = VECTOR_DB_CLIENT.search(
        collection_name=f'user-memory-{user.id}',
        vectors=[vector],
        limit=lim,
    )
    if not results or not results.ids or not results.ids[0]:
        return []

    ids = results.ids[0]
    dists = results.distances[0] if results.distances and results.distances[0] else [0.5] * len(ids)
    return rank_memory_hits(
        user_id=user.id,
        vector_ids=ids,
        vector_scores=dists,
        top_k=top_k,
        folder_scope_id=folder_scope_id,
        apply_folder_scope=apply_folder_scope,
    )


def rank_memory_hits(
    *,
    user_id: str,
    vector_ids: list[str],
    vector_scores: list[float],
    top_k: int,
    folder_scope_id: str | None = None,
    apply_folder_scope: bool = True,
) -> list[MemoryModel]:
    """Combine semantic similarity with importance/confidence/recency/usage."""
    if not vector_ids:
        return []
    scored: list[tuple[float, MemoryModel]] = []
    now = int(time.time())
    for i, mid in enumerate(vector_ids):
        m = Memories.get_memory_by_id(mid)
        if not m or m.user_id != user_id:
            continue
        if (m.status or 'active') != 'active':
            continue
        if apply_folder_scope and not memory_visible_in_folder_scope(m, folder_scope_id):
            continue
        raw_vec = vector_scores[i] if i < len(vector_scores) else 0.5
        sim = _normalize_vector_score(raw_vec)
        imp = float(m.importance_score or 0.5)
        conf = float(m.confidence_score or 0.5)
        age_days = max(0.0, (now - (m.updated_at or m.created_at)) / 86400.0)
        recency = _time_decay(age_days)
        use_boost = min(0.15, (int(m.access_count or 0) * 0.01))

        blend = (
            0.45 * sim
            + 0.20 * imp
            + 0.15 * conf
            + 0.15 * recency
            + 0.05 * use_boost
        )
        scored.append((blend, m))
    scored.sort(key=lambda x: -x[0])
    return [m for _, m in scored[:top_k]]
