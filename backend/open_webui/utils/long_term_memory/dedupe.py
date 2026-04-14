"""Near-duplicate detection for memory rows (lexical + optional semantic)."""

from __future__ import annotations

import difflib
import logging
import os
from typing import Any

from open_webui.utils.long_term_memory.safety import normalize_for_dedupe

log = logging.getLogger(__name__)


def best_fuzzy_match(
    candidate_norm: str,
    existing: list[dict[str, Any]],
    *,
    threshold: float = 0.86,
) -> dict[str, Any] | None:
    """Return existing memory dict if candidate is near-duplicate of one row."""
    if not candidate_norm or not existing:
        return None
    best: tuple[float, dict[str, Any]] | None = None
    for row in existing:
        content = row.get('normalized_content') or row.get('content') or ''
        n = normalize_for_dedupe(str(content))
        if not n:
            continue
        ratio = difflib.SequenceMatcher(a=candidate_norm, b=n).ratio()
        if best is None or ratio > best[0]:
            best = (ratio, row)
    if best and best[0] >= threshold:
        return best[1]
    return None


async def semantic_dedupe(
    candidate_text: str,
    user_id: str,
    *,
    request: Any,
    user: Any,
    threshold: float | None = None,
    top_k: int = 5,
) -> dict[str, Any] | None:
    """Use vector similarity to find a semantically duplicate memory.

    Returns the closest existing memory dict if cosine similarity >= threshold,
    or None if no near-duplicate is found.
    """
    if threshold is None:
        threshold = float(os.environ.get('LONG_TERM_MEMORY_SEMANTIC_DEDUPE_THRESHOLD', '0.92'))

    if not candidate_text or not candidate_text.strip():
        return None

    try:
        from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT
        from open_webui.models.memories import Memories

        vector = await request.app.state.EMBEDDING_FUNCTION(candidate_text, user=user)

        results = VECTOR_DB_CLIENT.search(
            collection_name=f'user-memory-{user_id}',
            vectors=[vector],
            limit=top_k,
        )

        if not results or not results.ids or not results.ids[0]:
            return None

        ids = results.ids[0]
        dists = results.distances[0] if results.distances and results.distances[0] else []

        for i, mid in enumerate(ids):
            score = dists[i] if i < len(dists) else 0.0
            if score >= threshold:
                mem = Memories.get_memory_by_id(mid)
                if mem and mem.user_id == user_id and (mem.status or 'active') == 'active':
                    return mem.model_dump()
        return None

    except Exception as e:
        log.debug('semantic_dedupe failed (falling back to fuzzy): %s', e)
        return None
