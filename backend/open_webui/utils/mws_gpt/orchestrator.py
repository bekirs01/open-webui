"""
MWS Auto orchestration: complexity estimation and tiered model selection.

Keeps a single user-facing completion by default; internal depth is metadata for routing/logging.
Optional multi-step flows (web search, image pipeline) remain in middleware.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    pass

Complexity = Literal['simple', 'medium', 'hard']

# Simple: quick factual / greeting / short turns — quality-first, strong models preferred
AUTO_TEXT_SIMPLE_ORDER: list[str] = [
    'qwen2.5-72b-instruct',
    'gpt-oss-120b',
    'llama-3.3-70b-instruct',
    'qwen3-32b',
    'mws-gpt-alpha',
    'gpt-oss-20b',
    'gemma-3-27b-it',
    'T-pro-it-1.0',
    'llama-3.1-8b-instruct',
]

# Balanced: default tier — general chat first; heavy reasoning models reserved for hard tier
AUTO_TEXT_MEDIUM_ORDER: list[str] = [
    'qwen2.5-72b-instruct',
    'llama-3.3-70b-instruct',
    'qwen3-32b',
    'gpt-oss-120b',
    'mws-gpt-alpha',
    'gpt-oss-20b',
    'gemma-3-27b-it',
    'T-pro-it-1.0',
    'llama-3.1-8b-instruct',
    'Qwen3-235B-A22B-Instruct-2507-FP8',
    'glm-4.6-357b',
    'kimi-k2-instruct',
    'deepseek-r1-distill-qwen-32b',
    'QwQ-32B',
]

# Reasoning-heavy (quality-first, deep thinkers at top)
AUTO_TEXT_HARD_ORDER: list[str] = [
    'Qwen3-235B-A22B-Instruct-2507-FP8',
    'glm-4.6-357b',
    'deepseek-r1-distill-qwen-32b',
    'QwQ-32B',
    'kimi-k2-instruct',
    'gpt-oss-120b',
    'qwen2.5-72b-instruct',
    'llama-3.3-70b-instruct',
    'qwen3-32b',
    'gpt-oss-20b',
    'gemma-3-27b-it',
    'T-pro-it-1.0',
]

_HARD_HINT = re.compile(
    r'\b(prove|proof|theorem|lemma|contradiction|formal\s+verification|axiom|rigorous|'
    r'peer.review|research\s+paper|literature\s+review|multi.step\s+(?:reasoning|analysis|proof)|'
    r'step.by.step\s+(?:proof|derivation|analysis)|'
    r'derive|derivation|epsilon.delta|bayesian\s+inference|optimize\s+globally|'
    r'pros?\s+(?:and|&)\s+cons?|'
    r'trade.?off\s+analysis|'
    r'write\s+(?:a|an)\s+(?:essay|article|report|paper|proposal)|'
    r'(?:essay|article|report|paper|proposal)\s+(?:yaz|oluştur|hazırla))\b',
    re.I,
)
_TR_HARD = re.compile(
    r'\b(kanıt(?:la|layın)|ispat(?:la)?|önerme|teorem|aksiyom|titiz\w*\s+(?:analiz|kanıt)|'
    r'adım\s+adım\s+(?:kanıtla|çöz|analiz|ispat)|çok\s+adımlı|'
    r'akademik\s+(?:makale|analiz|araştırma)|literatür\s+(?:tarama|inceleme)|'
    r'istatistiksel\s+anlamlılık|'
    r'derinlemesine\s+(?:analiz|karşılaştır)|kapsamlı\s+(?:analiz|rapor|değerlendir)|'
    r'makale\s+yaz|rapor\s+hazırla|'
    r'açıkla.{0,20}neden(?:leri)?|sebepleri\s+(?:analiz|açıkla))\b',
    re.I,
)
_CODE_HEAVY = re.compile(
    r'\b(refactor|architecture|distributed|concurrency|formal verification|'
    r'complexity analysis|big.?o|security audit|design pattern|'
    r'microservice|system design|scalab|high.?availab)\b',
    re.I,
)

# Medium: not trivial, needs more than a one-liner
_MEDIUM_HINT = re.compile(
    r'\b(explain|how\s+(?:does|do|to|can)|what\s+(?:is\s+the|are\s+the)|'
    r'why\s+(?:does|do|is|are)|difference|describe|summary|summarize|'
    r'overview|list\s+(?:the|all|some)|give\s+(?:me|an?)\s+(?:example|detail)|'
    r'translate|convert|implement)\b',
    re.I,
)
_TR_MEDIUM = re.compile(
    r'\b(açıkla|nasıl|neden|fark|özetle|listele|örnek ver|çevir|anlat|'
    r'tarif et|tanımla|göster|bilgi ver|yardım et)\b',
    re.I,
)


def orchestration_enabled(config: Any | None = None) -> bool:
    if config is not None and getattr(config, 'MWS_GPT_ORCHESTRATION', None) is not None:
        return bool(config.MWS_GPT_ORCHESTRATION)
    return os.environ.get('MWS_GPT_ORCHESTRATION', 'true').lower() == 'true'


_GREETING_SMALLTALK = re.compile(
    r'^(?:merhaba|selam|hey|hi|hello|günaydın|iyi\s+günler)[,\s!]*'
    r'.*\b(?:nasılsın|nasilsin|naber|ne haber|how\s+are\s+you)\b',
    re.I,
)
_TRIVIAL_GREETING_ONLY = re.compile(
    r'^(?:merhaba|selam|hey|hi|hello|günaydın|iyi\s+(?:akşamlar|günler)|'
    r'teşekkürler|teşekkür\s+ederim|sağ\s*ol|thanks?|thank\s+you|ok|okay|tamam|'
    r'evet|hayır|yes|no|anladım|peki)[!.,\s]*$',
    re.I,
)
_SIMPLE_FACTUAL = re.compile(
    r'^\s*(?:'
    r'(?:1|bir)\s+(?:tl|dolar|dollar|euro|ruble)\s+kaç|'
    r'kaç\s+(?:tl|dolar|dollar|euro|ruble)|'
    r'(?:bugün|şu\s*an)\s+(?:hava|saat)|'
    r'(?:how\s+much\s+is|what\s+is)\s+\d|'
    r'(?:\d+\s*[\+\-\*\/x]\s*\d+)|'
    r'(?:kim(?:dir)?|ne(?:dir)?|what\s+is|who\s+is)\s+\w'
    r')',
    re.I,
)


def estimate_complexity(
    *,
    message_text: str,
    modality: str,
    attachments: set[str],
) -> tuple[Complexity, str]:
    """
    Heuristic task depth for Auto text/code routing (not for vision/audio/image).
    Prefers 'medium' as default — 'simple' only for truly trivial turns.
    """
    t = (message_text or '').strip()
    if modality not in ('text', 'code'):
        return 'medium', 'modality_non_text'

    # Short greetings / smalltalk — avoid classifying as "medium" via TR "nasıl" heuristics
    if len(t) < 200 and _GREETING_SMALLTALK.search(t):
        return 'simple', 'short_greeting_smalltalk'
    if len(t) < 80 and _TRIVIAL_GREETING_ONLY.match(t.strip()):
        return 'simple', 'trivial_greeting_only'
    if len(t) < 120 and _SIMPLE_FACTUAL.search(t):
        return 'simple', 'simple_factual_question'

    if len(t) > 3500 or t.count('\n') > 40:
        return 'hard', 'long_context'

    if modality == 'code' and (_CODE_HEAVY.search(t) or len(t) > 2000):
        return 'hard', 'code_heavy'

    if _HARD_HINT.search(t) or _TR_HARD.search(t):
        return 'hard', 'reasoning_keywords'

    if _MEDIUM_HINT.search(t) or _TR_MEDIUM.search(t):
        return 'medium', 'explanation_or_detail_keywords'

    word_count = len(t.split())
    has_question = '?' in t

    if len(t) < 80 and word_count <= 8 and not has_question:
        return 'simple', 'very_short_greeting_or_command'

    if len(t) < 150 and t.count('?') <= 1 and '\n' not in t and word_count <= 12:
        return 'simple', 'short_trivial_turn'

    return 'medium', 'default'


def pick_auto_text_by_complexity(
    available: set[str],
    complexity: Complexity,
) -> tuple[str | None, str | None]:
    """First available model id from tiered text lists."""
    from open_webui.utils.mws_gpt.team_registry import (
        filter_team_available,
        first_available,
    )

    av = filter_team_available(available)
    if not av:
        return None, 'MWS: no team-allowed models in available set.'

    order: list[str]
    if complexity == 'simple':
        order = AUTO_TEXT_SIMPLE_ORDER
    elif complexity == 'hard':
        order = AUTO_TEXT_HARD_ORDER
    else:
        order = AUTO_TEXT_MEDIUM_ORDER

    pick = first_available(order, av)
    if pick:
        return pick, None
    # Fallback: any text-capable
    from open_webui.utils.mws_gpt.team_registry import get_primary_capability

    for mid in sorted(av):
        if get_primary_capability(mid) == 'text':
            return mid, 'MWS: complexity tier miss; used text fallback.'
    if av:
        return next(iter(sorted(av))), 'MWS: unexpected fallback to first available.'
    return None, None
