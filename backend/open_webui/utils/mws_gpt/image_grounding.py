"""
Research-grounded image generation: detect real-world draw requests and inject web facts into image prompts.
"""

from __future__ import annotations

import logging
import re
from typing import Any


log = logging.getLogger(__name__)

# Same structure as url_page_context — consumed by split_url_injected_grounding in image_prompt.py
_GROUNDING_HEADER = '### Web research (visual grounding)'
_GROUNDING_FOOTER = '\n\n---\n\n**User message:**\n\n'


def wants_research_grounded_image_prompt(message_text: str) -> bool:
    """
    True when the user is asking to draw/visualize something that likely refers to a real-world
    person, place, institution, landmark, or brand — where web grounding helps fidelity.

    False for simple fictional one-liners (e.g. "mavi kedi çiz") when no real entity is implied.
    """
    from open_webui.utils.mws_gpt.registry import _normalize_tr_keyboard_typos, _wants_image_creation

    t = _normalize_tr_keyboard_typos((message_text or '').strip())
    if not t or len(t) > 4000:
        return False
    low = t.lower()

    # Must be an image-creation style request
    if not (
        _wants_image_creation(t)
        or re.search(r'\b(?:çiz|ciz|draw|paint|sketch|resim\s|görsel|illüstrasyon|нарисуй|изобрази)\b', low)
    ):
        return False

    if _is_simple_fictional_image_prompt(low, t):
        return False

    # Explicit real-world / deictic references (TR: şu adamı, bu gerçek kişiyi, şu ünlü kişiyi)
    if re.search(
        r'(?:şu|bu)\s+(?:adamı|kadını|kişiyi|kişi|üniversiteyi|üniversite|üniversitesini|'
        r'okulu|okulunu|yeri|bina|mekanı|fotoğrafı|ünlüyü|ünlü\s+kişiyi|meşhuru|meşhur\s+kişiyi)\b',
        low,
    ):
        return True
    if re.search(
        r'\b(?:bu|şu)\s+(?:gerçek|real)\s+(?:kişiyi|kişi|insanı)\b',
        low,
    ):
        return True
    if re.search(
        r'\b(?:gerçek|real|actual)\s+(?:kişi|person|building|place|university|landmark)\b',
        low,
    ):
        return True

    # Landmarks / brands / iconic places (short queries; web search disambiguates)
    if re.search(
        r'\b(?:kremlin|кремль|eyfel|eiffel|taj\s+mahal|big\s+ben|colosseum|kolezyum|'
        r'ayasofya|hagia\s+sophia|statue\s+of\s+liberty|brand|logo|headquarters|hq\b|'
        r'skyscraper|gökdelen)\b',
        low,
        re.I,
    ):
        return True

    # Institutions / geography (multilingual)
    if re.search(
        r'\b(?:university|universit|üniversite|college|campus|kampüs|федеральн|университет|институт|'
        r'harvard|stanford|oxford|cambridge|mit\b|федеральный|جامعة|جامعه|كلية|معهد)\b',
        low,
        re.I,
    ):
        return True

    # Multi-word English proper names (Title Case segments)
    if re.search(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,5}\b', t):
        return True

    # Turkish-style multi-token names with capital İ/I or common surname particles
    if re.search(
        r'[A-ZÇĞİÖŞÜ][a-zçğıöşü]+\s+[A-ZÇĞİÖŞÜ]?[a-zçğıöşü]+',
        t,
    ):
        return True

    # Russian / Arabic script blocks (likely named entities)
    if re.search(r'[\u0400-\u04FF]{6,}', t) or re.search(r'[\u0600-\u06FF]{8,}', t):
        return True

    return False


def _is_simple_fictional_image_prompt(low: str, raw: str) -> bool:
    """Short generic prompts that do not need web research."""
    if len(raw) > 220:
        return False
    # "mavi kedi çiz", "a red car", "blue sky"
    if re.match(
        r'^[\s,;:!]*(?:a\s+|an\s+|bir\s+)?'
        r'(?:mavi|kırmızı|yeşil|sarı|beyaz|siyah|blue|red|green|yellow|white|black)\s+'
        r'(?:kedi|köpek|araba|uçak|ev|ağaç|cat|dog|car|house|tree)\b',
        low,
    ):
        return True
    if re.match(
        r'^[\s,;:!]*(?:bir\s+)?(?:ejderha|dragon|unicorn|peri|fantasy|hayali)\b',
        low,
    ):
        return True
    return False


def _snippet_from_web_files(files: list[dict[str, Any]]) -> str:
    """Fast path when BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL embedded docs in the file item."""
    chunks: list[str] = []
    for f in files:
        if f.get('type') != 'web_search':
            continue
        for d in (f.get('docs') or [])[:12]:
            if not isinstance(d, dict):
                continue
            c = (d.get('content') or '').strip()
            if c:
                chunks.append(c[:1200])
    return '\n\n'.join(chunks).strip()


def _flatten_rag_sources(sources: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for s in sources or []:
        for doc in s.get('document') or []:
            if isinstance(doc, str) and doc.strip():
                parts.append(doc.strip())
    text = '\n\n'.join(parts)
    if len(text) > 3200:
        text = text[:3200].rsplit('\n', 1)[0] + '\n[trimmed]'
    return text


async def inject_web_research_text_into_last_user_message(
    request: Any,
    form_data: dict[str, Any],
    user: Any,
) -> None:
    """
    After chat_web_search_handler, merge retrieved web text into the last user message using
    the same delimiter pattern as URL page context so build_mws_image_prompt picks up grounding.
    """
    files = [f for f in (form_data.get('files') or []) if isinstance(f, dict) and f.get('type') == 'web_search']
    if not files:
        return

    blob = _snippet_from_web_files(files)
    if not blob:
        try:
            from open_webui.retrieval.utils import get_sources_from_items

            um = ''
            try:
                from open_webui.utils.misc import get_last_user_message

                um = get_last_user_message(form_data.get('messages') or []) or ''
            except Exception:
                pass
            queries = [um] if (um and um.strip()) else ['image subject reference']

            sources = await get_sources_from_items(
                request=request,
                items=files,
                queries=queries,
                embedding_function=lambda query, prefix: request.app.state.EMBEDDING_FUNCTION(
                    query, prefix=prefix, user=user
                ),
                k=request.app.state.config.TOP_K,
                reranking_function=(
                    (lambda query, documents: request.app.state.RERANKING_FUNCTION(query, documents, user=user))
                    if request.app.state.RERANKING_FUNCTION
                    else None
                ),
                k_reranker=request.app.state.config.TOP_K_RERANKER,
                r=request.app.state.config.RELEVANCE_THRESHOLD,
                hybrid_bm25_weight=request.app.state.config.HYBRID_BM25_WEIGHT,
                hybrid_search=request.app.state.config.ENABLE_RAG_HYBRID_SEARCH,
                full_context=False,
                user=user,
            )
            blob = _flatten_rag_sources(sources)
        except Exception as e:
            log.debug('[MWS] image grounding RAG: %s', e)
            return

    if not blob.strip():
        return

    try:
        from open_webui.utils.mws_gpt.registry import extract_last_user_text
        from open_webui.utils.misc import set_last_user_message_content

        original = extract_last_user_text(form_data.get('messages') or [])
        if not original.strip():
            return
        wrapped = (
            f'{_GROUNDING_HEADER}\n\n'
            'GROUNDING RULES: Use only the facts below for recognizable architecture, colors, materials, and setting. '
            'If the user asked for a building or campus, show that structure as the main subject—no random pedestrians, '
            'cyclists, or vehicles in the foreground unless the user asked. '
            'If the user asked for a specific public figure, match general appearance conservatively; do not invent a different person. '
            'Do not add crowds, extra faces, or unrelated props.\n\n'
            f'{blob.strip()}'
            f'{_GROUNDING_FOOTER}{original.strip()}'
        )
        set_last_user_message_content(wrapped, form_data.get('messages') or [])
    except Exception as e:
        log.warning('[MWS] inject_web_research_text_into_last_user_message: %s', e)
