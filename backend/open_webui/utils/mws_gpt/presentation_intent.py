"""
Detect user intent to create a presentation (MWS — gated by caller).

Supports RU/EN/TR including phrases with words BETWEEN the verb and «презентация»
(e.g. «создай короткую презентацию про кошек» — the old regex required them adjacent).
"""

from __future__ import annotations

import re


def resolve_presentation_intent(message_text: str) -> bool:
    t = (message_text or '').strip()
    if not t or len(t) > 12000:
        return False

    low = t.lower()

    # Academic / definition questions — not "make me a deck"
    if re.match(
        r'^\s*(?:что\s+такое|как\s+сделать\s+презентац|what\s+is|how\s+to\s+make\s+a\s+presentation|nedir|explain)\b',
        t,
        re.I,
    ):
        return False

    # Must mention a deck-like object (RU/EN/TR)
    has_deck_keyword = bool(
        re.search(r'презентац', low)
        or re.search(r'\bpresentation\b', low)
        or re.search(r'\b(?:slide|slides)\b', low)
        or re.search(r'\bdeck\b', low)
        or re.search(r'\bsunum\b', low)
    )
    if not has_deck_keyword:
        return False

    # Creation / request signals (verb may be several words before «презентация»)
    create_ru = re.search(
        r'\b(?:созда[ййи]|сдела[ййи]|подготовь|сгенерируй|напиши|оформи|составь)\b'
        r'(?:\s+[^\n]{0,72})?'
        r'\bпрезентац',
        t,
        re.I,
    )
    create_ru_inf = re.search(
        r'\b(?:создать|сделать|подготовить)\b(?:\s+[^\n]{0,72})?\bпрезентац',
        t,
        re.I,
    )
    need_deck_ru = re.search(
        r'\b(?:нужна|нужен|требуется)\s+(?:мне\s+)?(?:коротк(?:ая|ую|ой)|небольш(?:ая|ую|ой)|)\s*презентац',
        t,
        re.I,
    )
    slides_ru = re.search(
        r'\b(?:созда[ййи]|сдела[ййи])\b(?:\s+[^\n]{0,48})?\bслайд',
        t,
        re.I,
    )

    create_en = re.search(
        r'\b(?:create|make|build|generate)\b(?:\s+[^\n]{0,72})?\b(?:presentation|slide\s+deck)\b',
        t,
        re.I,
    )
    tr = re.search(
        r'(?:sunum\s+(?:oluştur|hazırla|yap)|bir\s+sunum\s+(?:oluştur|hazırla|yap))',
        t,
        re.I,
    )

    return bool(
        create_ru or create_ru_inf or need_deck_ru or slides_ru or create_en or tr
    )
