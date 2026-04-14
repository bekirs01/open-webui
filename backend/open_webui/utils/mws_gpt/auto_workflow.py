"""
MWS Auto: multi-step workflow metadata (vision→text, code→review, etc.).

Execution is applied in workflow_runner.apply_mws_auto_workflow_preflight.
"""

from __future__ import annotations

import os
from typing import Any

from open_webui.utils.mws_gpt.orchestrator import pick_auto_text_by_complexity
from open_webui.utils.mws_gpt.team_registry import (
    filter_team_available,
    first_available,
    get_primary_capability,
)
from open_webui.utils.workspace_system_prompt import WORKSPACE_AUTO_SYNTHESIS_SYSTEM_PROMPT


def multi_model_auto_enabled(config: Any | None = None) -> bool:
    if config is not None and getattr(config, 'MWS_AUTO_MULTI_MODEL', None) is not None:
        return bool(config.MWS_AUTO_MULTI_MODEL)
    return os.environ.get('MWS_AUTO_MULTI_MODEL', 'true').lower() == 'true'


def code_review_enabled() -> bool:
    return os.environ.get('MWS_AUTO_CODE_REVIEW', 'false').lower() == 'true'


def vision_synthesis_enabled() -> bool:
    return os.environ.get('MWS_AUTO_VISION_SYNTHESIS', 'true').lower() == 'true'


def deep_thinking_text_polish_enabled() -> bool:
    """Second pass (drafter → polisher) when UI enables Deep thinking."""
    return os.environ.get('MWS_DEEP_THINKING_MULTI', 'true').lower() == 'true'


# Reviewer / polish models (after code draft or heavy reasoning)
# Import from central registry to keep in sync
from open_webui.utils.mws_gpt.team_registry import AUTO_REVIEWER_ORDER


def build_auto_workflow(
    *,
    decision: dict[str, Any],
    available: set[str],
    config: Any,
    message_text: str,
    attachments: set[str],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Returns workflow dict stored under routing meta orchestration.workflow.
    kind: single | vision_then_text | code_then_review | text_then_polish
    """
    if not multi_model_auto_enabled(config):
        return {'kind': 'single', 'steps': 1}

    modality = decision.get('modality')
    complexity = decision.get('complexity')
    primary = decision.get('model_id')
    av = filter_team_available(available)
    px = params or {}

    if modality == 'export':
        return {'kind': 'single', 'steps': 1}

    # Deep thinking (UI): strong text drafter → polisher / reviewer
    if (
        deep_thinking_text_polish_enabled()
        and px.get('mws_deep_thinking')
        and modality == 'text'
        and primary
        and get_primary_capability(primary) == 'text'
    ):
        polisher = first_available(AUTO_REVIEWER_ORDER, av)
        if polisher and polisher != primary:
            return {
                'kind': 'text_then_polish',
                'steps': 2,
                'drafter_model_id': primary,
                'polisher_model_id': polisher,
            }

    # Vision: görsel ek + soru → önce VL, sonra metin sentez
    if (
        vision_synthesis_enabled()
        and modality == 'vision'
        and 'image' in (attachments or set())
        and primary
        and get_primary_capability(primary) == 'vision'
    ):
        synth, _ = pick_auto_text_by_complexity(av, 'medium')
        if not synth:
            synth = first_available(AUTO_REVIEWER_ORDER, av)
        if synth and synth != primary:
            return {
                'kind': 'vision_then_text',
                'steps': 2,
                'vision_model_id': primary,
                'synthesizer_model_id': synth,
            }

    # Kod: zor görev veya Deep thinking → taslak + inceleme (ortam ile)
    if (
        code_review_enabled()
        and modality == 'code'
        and (complexity == 'hard' or px.get('mws_deep_thinking'))
        and primary
        and get_primary_capability(primary) == 'code'
    ):
        reviewer = first_available(AUTO_REVIEWER_ORDER, av)
        if reviewer and reviewer != primary:
            return {
                'kind': 'code_then_review',
                'steps': 2,
                'code_model_id': primary,
                'reviewer_model_id': reviewer,
            }

    return {'kind': 'single', 'steps': 1}


AUTO_FINAL_SYNTHESIS_SYSTEM = WORKSPACE_AUTO_SYNTHESIS_SYSTEM_PROMPT
