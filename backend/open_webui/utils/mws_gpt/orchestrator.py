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

# Fast, capable defaults (latency-first)
AUTO_TEXT_SIMPLE_ORDER: list[str] = [
    'llama-3.3-70b-instruct',
    'llama-3.1-8b-instruct',
    'gemma-3-27b-it',
    'gpt-oss-20b',
    'qwen3-32b',
    'mws-gpt-alpha',
]

# Balanced (previous default chain)
AUTO_TEXT_MEDIUM_ORDER: list[str] = [
    'llama-3.3-70b-instruct',
    'glm-4.6-357b',
    'Qwen3-235B-A22B-Instruct-2507-FP8',
    'qwen3-32b',
    'mws-gpt-alpha',
    'gpt-oss-120b',
    'gpt-oss-20b',
    'deepseek-r1-distill-qwen-32b',
    'gemma-3-27b-it',
    'llama-3.1-8b-instruct',
    'QwQ-32B',
    'qwen2.5-72b-instruct',
    'kimi-k2-instruct',
    'T-pro-it-1.0',
]

# Reasoning-heavy (quality-first)
AUTO_TEXT_HARD_ORDER: list[str] = [
    'deepseek-r1-distill-qwen-32b',
    'QwQ-32B',
    'Qwen3-235B-A22B-Instruct-2507-FP8',
    'gpt-oss-120b',
    'glm-4.6-357b',
    'llama-3.3-70b-instruct',
    'qwen3-32b',
    'gpt-oss-20b',
    'kimi-k2-instruct',
    'gemma-3-27b-it',
    'T-pro-it-1.0',
]

_HARD_HINT = re.compile(
    r'\b(prove|proof|theorem|lemma|contradiction|formal|axiom|rigorous|'
    r'peer.review|research paper|literature review|multi.step|step.by.step|'
    r'derive|derivation|epsilon.delta|bayesian inference|optimize globally)\b',
    re.I,
)
_TR_HARD = re.compile(
    r'\b(kanıt|ispat|önerme|teorem|aksiyom|titiz|adım adım|çok adımlı|'
    r'akademik|literatür|araştırma|olasılık|istatistiksel anlamlılık)\b',
    re.I,
)
_CODE_HEAVY = re.compile(
    r'\b(refactor|architecture|distributed|concurrency|formal verification|'
    r'complexity analysis|big.?o|security audit)\b',
    re.I,
)


def orchestration_enabled(config: Any | None = None) -> bool:
    if config is not None and getattr(config, 'MWS_GPT_ORCHESTRATION', None) is not None:
        return bool(config.MWS_GPT_ORCHESTRATION)
    return os.environ.get('MWS_GPT_ORCHESTRATION', 'true').lower() == 'true'


def estimate_complexity(
    *,
    message_text: str,
    modality: str,
    attachments: set[str],
) -> tuple[Complexity, str]:
    """
    Heuristic task depth for Auto text/code routing (not for vision/audio/image).
    """
    t = (message_text or '').strip()
    if modality not in ('text', 'code'):
        return 'medium', 'modality_non_text'

    if len(t) > 3500 or t.count('\n') > 40:
        return 'hard', 'long_context'

    if modality == 'code' and (_CODE_HEAVY.search(t) or len(t) > 2000):
        return 'hard', 'code_heavy'

    if _HARD_HINT.search(t) or _TR_HARD.search(t):
        return 'hard', 'reasoning_keywords'

    if len(t) < 100 and t.count('?') <= 1 and '\n' not in t:
        return 'simple', 'short_turn'

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
