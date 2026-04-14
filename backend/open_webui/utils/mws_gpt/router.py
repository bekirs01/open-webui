"""
MWS GPT auto-router: Auto is a mode (sentinel id `auto`), never sent upstream.
Legacy `mws:auto` is accepted and normalized to the same behavior.

Routing decision pipeline:
  1. classify_task_modality → deterministic modality (text/code/vision/image_generation/…)
  2. estimate_complexity → simple/medium/hard (text/code only)
  3. pick model from tiered priority lists
  4. build workflow metadata (single/vision_then_text/code_then_review/text_then_polish)
  5. return structured RoutingDecision with confidence + fallback
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from open_webui.utils.mws_gpt.registry import (
    classify_task_modality,
    collect_attachment_kinds,
    extract_last_user_text,
    wants_web_research_heavy_task,
)
from open_webui.utils.mws_gpt.orchestrator import (
    estimate_complexity,
    orchestration_enabled,
    pick_auto_text_by_complexity,
)
from open_webui.utils.mws_gpt.auto_workflow import build_auto_workflow
from open_webui.utils.mws_gpt.team_registry import (
    MODEL_CAPABILITIES,
    filter_team_available,
    get_primary_capability,
    pick_auto_target_model,
    team_allowlist_enabled,
)
from open_webui.utils.mws_gpt.routing_tasks import classify_detailed_task
from open_webui.utils.mws_gpt.intelligence.pipeline import build_routing_input
from open_webui.utils.mws_gpt.intelligence.safety import evaluate_image_generation_safety
from open_webui.utils.mws_gpt.intelligence.fallback_engine import build_fallback_chain
from open_webui.utils.mws_gpt.intelligence.policy_packs import policy_pack_for_modality

log = logging.getLogger(__name__)

MWS_AUTO_ID = 'auto'
LEGACY_AUTO_IDS = frozenset({'auto', 'mws:auto'})

# Confidence thresholds for routing quality
_CONF_HIGH = 0.95
_CONF_MEDIUM = 0.80
_CONF_LOW = 0.60


@dataclass
class RoutingDecision:
    """Structured, inspectable routing decision object.

    *primary_task* is the coarse execution modality (text/code/vision/…).
    *detailed_task* is the fine-grained taxonomy label (text_chat, reasoning, …).
    """

    primary_task: str
    input_modalities: list[str]
    output_modalities: list[str]
    selected_model: str | None
    fallback_model: str | None = None
    confidence: float = _CONF_MEDIUM
    reason: str = ''
    modality_reason: str = ''
    complexity: str | None = None
    complexity_reason: str | None = None
    detailed_task: str = 'unknown'
    secondary_tasks: list[str] = field(default_factory=list)
    requires_tools: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    timestamp_ms: int = 0
    normalized_routing_text: str = ''
    normalization_steps: tuple[str, ...] = ()
    safety_block: str | None = None
    fallback_chain: list[str] = field(default_factory=list)
    policy_pack_id: str = ''

    def to_dict(self) -> dict[str, Any]:
        return {
            'primary_task': self.primary_task,
            'detailed_task': self.detailed_task,
            'secondary_tasks': list(self.secondary_tasks),
            'requires_tools': list(self.requires_tools),
            'input_modalities': self.input_modalities,
            'output_modalities': self.output_modalities,
            'selected_model': self.selected_model,
            'fallback_model': self.fallback_model,
            'fallback_chain': list(self.fallback_chain),
            'confidence': self.confidence,
            'reason': self.reason,
            'modality_reason': self.modality_reason,
            'complexity': self.complexity,
            'complexity_reason': self.complexity_reason,
            'warnings': self.warnings,
            'timestamp_ms': self.timestamp_ms,
            'normalized_routing_text': self.normalized_routing_text,
            'normalization_steps': list(self.normalization_steps),
            'safety_block': self.safety_block,
            'policy_pack_id': self.policy_pack_id,
        }


def _compute_confidence(modality: str, mod_reason: str, pick: str | None, complexity: str | None) -> float:
    """Heuristic confidence score for the routing decision."""
    if not pick:
        return 0.0

    mc = MODEL_CAPABILITIES.get(pick)
    cap = get_primary_capability(pick) if pick else None

    # Perfect match: model's primary capability matches requested modality
    if modality == 'image_generation' and cap == 'image_generation':
        return _CONF_HIGH
    if modality == 'vision' and cap == 'vision':
        return _CONF_HIGH
    if modality == 'code' and cap == 'code':
        return _CONF_HIGH
    if modality == 'text' and cap == 'text':
        if mod_reason == 'memory_or_context_question':
            return _CONF_HIGH
        if complexity == 'hard' and mc and mc.supports_reasoning:
            return _CONF_HIGH
        return 0.90
    if modality == 'export' and cap == 'text':
        return 0.85

    # Mismatch penalties
    if modality == 'code' and cap == 'text':
        return _CONF_LOW + 0.10
    if modality == 'text' and cap in ('vision', 'code'):
        return _CONF_LOW

    return _CONF_MEDIUM


def _safety_gate_enabled(config: Any) -> bool:
    o = getattr(config, 'MWS_AUTO_ROUTER_SAFETY_ENABLED', None)
    if o is not None:
        return bool(getattr(o, 'value', o))
    return os.environ.get('MWS_AUTO_ROUTER_SAFETY_ENABLED', 'true').lower() == 'true'


def _pick_fallback(modality: str, selected: str | None, available: set[str]) -> str | None:
    """Pick a fallback model different from the selected one."""
    mc = MODEL_CAPABILITIES.get(selected) if selected else None
    if mc and mc.fallback_candidates:
        for fb in mc.fallback_candidates:
            if fb in available and fb != selected:
                return fb

    text_pick, _ = pick_auto_target_model('text', available)
    if text_pick and text_pick != selected:
        return text_pick
    return None


def _infer_output_modalities(modality: str) -> list[str]:
    if modality == 'image_generation':
        return ['image']
    if modality == 'audio_transcription':
        return ['text']
    return ['text']


def _infer_input_modalities(attachments: set[str]) -> list[str]:
    mods = ['text']
    if 'image' in attachments:
        mods.append('image')
    if 'audio' in attachments:
        mods.append('audio')
    if 'document' in attachments:
        mods.append('document')
    return mods


def _available_mws_model_ids(openai_models: dict[str, dict[str, Any]]) -> set[str]:
    return {k for k in (openai_models or {}) if k}


def decide_mws_model(
    *,
    manual_model_id: str | None,
    message_text: str,
    attachments: set[str],
    input_mode: str | None,
    openai_models: dict[str, dict[str, Any]],
    config: Any,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    If manual_model_id is Auto (auto or mws:auto), pick a real model from team rules + availability.
    Otherwise manual override returns the same id (caller validates allowlist).

    Returns a dict with keys: model_id, reason, modality, warnings, complexity, complexity_reason,
    plus a 'routing_decision' key containing the full RoutingDecision object.
    """
    t_start = int(time.time() * 1000)
    mid = (manual_model_id or '').strip()
    if mid not in LEGACY_AUTO_IDS:
        return {
            'model_id': mid or None,
            'reason': 'manual_override',
            'modality': None,
            'warnings': [],
        }

    available_all = _available_mws_model_ids(openai_models)
    available = set(available_all)
    allowlist_route_warnings: list[str] = []
    if team_allowlist_enabled():
        flt = filter_team_available(available)
        if flt:
            available = flt
        elif available_all:
            # TEAM_ALLOWLIST ids must match live /models ids exactly; if intersection is empty,
            # still route Auto using the provider snapshot (otherwise we fall through to
            # MWS_GPT_DEFAULT_TEXT_MODEL and often 404 / "Model not found").
            available = set(available_all)
            allowlist_route_warnings.append(
                'MWS: team allowlist ∩ /models empty; using full provider model id set for Auto.'
            )

    if not getattr(config, 'MWS_GPT_AUTO_ROUTING', None) or not config.MWS_GPT_AUTO_ROUTING:
        pick, w = pick_auto_target_model('text', available, available_unfiltered=available_all)
        warnings = [w] if w else []
        if not pick:
            fb = (getattr(config, 'MWS_GPT_DEFAULT_TEXT_MODEL', None) or '').strip()
            if fb and fb in available_all:
                pick = fb
                warnings.append('MWS: auto-routing off; using MWS_GPT_DEFAULT_TEXT_MODEL.')
        log.info('[MWS] auto-routing disabled; model=%s warnings=%s', pick, warnings)
        return {
            'model_id': pick,
            'reason': 'auto_disabled_use_text_default',
            'modality': 'text',
            'warnings': [x for x in warnings if x],
        }

    # LAYER A–C: Normalized routing text + task classification (UI message unchanged)
    n_in = build_routing_input(message_text, config)
    rt = n_in.text_for_classification

    modality, mod_reason = classify_task_modality(
        message_text=message_text,
        attachments=attachments,
        input_mode=input_mode,
        enable_image_edit=getattr(config, 'ENABLE_IMAGE_EDIT', False),
        routing_text=rt,
    )

    safety_block: str | None = None
    pre_warnings: list[str] = list(allowlist_route_warnings)
    # Block disallowed content for any modality (Auto must not bypass safety via weak heuristics).
    if _safety_gate_enabled(config):
        sg = evaluate_image_generation_safety(rt)
        if not sg.allowed:
            modality, mod_reason = 'text', f'safety_redirect_{sg.reason_code or "blocked"}'
            safety_block = sg.reason_code
            pre_warnings.append(
                f'MWS: request blocked by safety policy ({sg.reason_code}).'
            )

    px = params or {}
    deep = bool(px.get('mws_deep_thinking'))

    complexity: str | None = None
    complexity_reason: str | None = None

    # LAYER 3: Capability-aware model selection
    if modality == 'text' and orchestration_enabled(config):
        if deep:
            complexity, complexity_reason = 'hard', 'mws_deep_thinking'
            pick, warn = pick_auto_text_by_complexity(available, 'hard')
        else:
            complexity, complexity_reason = estimate_complexity(
                message_text=rt,
                modality=modality,
                attachments=attachments,
            )
            # Do not promote trivial greetings ("bugün nasılsın") to medium via fresh-news heuristics
            if complexity == 'simple' and complexity_reason not in (
                'short_greeting_smalltalk',
                'trivial_greeting_only',
                'very_short_greeting_or_command',
                'short_trivial_turn',
            ) and wants_web_research_heavy_task(rt):
                complexity, complexity_reason = 'medium', 'web_research_intent'
            pick, warn = pick_auto_text_by_complexity(available, complexity)
        warnings = [warn] if warn else []
        warnings = pre_warnings + warnings
        log.info(
            '[MWS-Router] task=%s complexity=%s (%s) -> model=%s',
            modality, complexity, complexity_reason, pick,
        )
    elif modality == 'export' and orchestration_enabled(config):
        complexity, complexity_reason = 'simple', 'export_turn'
        pick, warn = pick_auto_text_by_complexity(available, 'simple')
        warnings = pre_warnings + ([warn] if warn else [])
    elif modality == 'code' and orchestration_enabled(config) and deep:
        complexity, complexity_reason = 'hard', 'mws_deep_thinking'
        pick, warn = pick_auto_target_model(modality, available, available_unfiltered=available_all)
        warnings = pre_warnings + ([warn] if warn else [])
    else:
        pick, warn = pick_auto_target_model(modality, available, available_unfiltered=available_all)
        warnings = pre_warnings + ([warn] if warn else [])

    # LAYER 4: Fallback (do not route image intents to a text model)
    if not pick:
        if modality == 'image_generation':
            fb_img = (getattr(config, 'MWS_GPT_DEFAULT_IMAGE_MODEL', None) or '').strip()
            if fb_img:
                pick = fb_img
                warnings.append('MWS: Auto using MWS_GPT_DEFAULT_IMAGE_MODEL (no image id resolved from /models).')
        if not pick:
            pick, w2 = pick_auto_target_model('text', available, available_unfiltered=available_all)
            if w2:
                warnings.append(w2)
            log.warning('[MWS-Router] auto-route failed for %s; text fallback=%s', modality, pick)

    if not pick:
        fb = (getattr(config, 'MWS_GPT_DEFAULT_TEXT_MODEL', None) or '').strip()
        if fb and fb in available_all:
            pick = fb
            warnings.append('MWS: used MWS_GPT_DEFAULT_TEXT_MODEL as last resort.')
        elif fb:
            warnings.append(
                f'MWS: MWS_GPT_DEFAULT_TEXT_MODEL {fb!r} not in current /models; skipped.'
            )

    if not pick and available_all:
        pick = sorted(available_all)[0]
        warnings.append('MWS: last resort — first model id from live /models snapshot.')

    fallback = _pick_fallback(modality, pick, available)
    fb_chain = build_fallback_chain(modality, pick, available)
    confidence = _compute_confidence(modality, mod_reason, pick, complexity)
    if safety_block:
        confidence = min(confidence, 0.55)

    detailed, secondary_tasks, requires_tools = classify_detailed_task(
        modality=modality,
        modality_reason=mod_reason,
        message_text=rt,
        attachments=attachments,
        complexity=complexity,
    )

    rd = RoutingDecision(
        primary_task=modality,
        input_modalities=_infer_input_modalities(attachments),
        output_modalities=_infer_output_modalities(modality),
        selected_model=pick,
        fallback_model=fallback,
        confidence=confidence,
        reason=f'auto:{mod_reason}',
        modality_reason=mod_reason,
        complexity=complexity,
        complexity_reason=complexity_reason,
        detailed_task=detailed,
        secondary_tasks=secondary_tasks,
        requires_tools=requires_tools,
        warnings=[x for x in warnings if x],
        timestamp_ms=t_start,
        normalized_routing_text=rt,
        normalization_steps=n_in.steps_applied,
        safety_block=safety_block,
        fallback_chain=fb_chain,
        policy_pack_id=policy_pack_for_modality(modality),
    )

    try:
        log.info('[MWS-Routing-JSON] %s', json.dumps(rd.to_dict(), ensure_ascii=False, default=str))
    except Exception:
        log.info('[MWS-Routing-JSON] <serialization_failed>')

    log.info(
        '[MWS-Router] per_turn task=%s complexity=%s detailed=%s model=%s fb=%s chain_head=%s',
        rd.primary_task,
        rd.complexity,
        rd.detailed_task,
        rd.selected_model,
        rd.fallback_model,
        (rd.fallback_chain[:3] if rd.fallback_chain else []),
    )
    log.info(
        '[MWS-Router] decision: task=%s detailed=%s model=%s confidence=%.2f reason=%s fallback=%s',
        rd.primary_task, rd.detailed_task, rd.selected_model, rd.confidence, rd.reason, rd.fallback_model,
    )

    return {
        'model_id': pick,
        'reason': f'auto:{mod_reason}',
        'modality': modality,
        'warnings': rd.warnings,
        'complexity': complexity,
        'complexity_reason': complexity_reason,
        'routing_decision': rd.to_dict(),
    }


def resolve_mws_chat_model(
    request: Any,
    form_data: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    """
    Replace Auto sentinel with a real model id. Never returns auto/mws:auto.
    """
    from open_webui.utils.mws_gpt.active import is_mws_gpt_active

    config = request.app.state.config
    if not is_mws_gpt_active(config):
        return form_data.get('model') or '', None

    mid = (form_data.get('model') or '').strip()
    if mid not in LEGACY_AUTO_IDS:
        return mid, None

    models = request.app.state.OPENAI_MODELS or {}
    mws_models = {
        k: v
        for k, v in models.items()
        if _is_mws_tagged_model(v, getattr(config, 'MWS_GPT_TAG', 'mws'))
    }
    if not mws_models:
        mws_models = models

    text = extract_last_user_text(form_data.get('messages') or [])
    att = collect_attachment_kinds(form_data.get('files'), form_data.get('messages'))
    input_mode = form_data.get('input_mode') or form_data.get('params', {}).get('input_mode')

    decision = decide_mws_model(
        manual_model_id=mid,
        message_text=text,
        attachments=att,
        input_mode=input_mode,
        openai_models=mws_models,
        config=config,
        params=form_data.get('params') or {},
    )

    resolved = decision.get('model_id')
    fb = (getattr(config, 'MWS_GPT_DEFAULT_TEXT_MODEL', None) or '').strip()
    if not resolved and fb and fb in (mws_models or {}):
        resolved = fb
        log.warning('[MWS] resolver empty; trying MWS_GPT_DEFAULT_TEXT_MODEL=%s', fb)

    full_models = getattr(request.app.state, 'MODELS', None) or {}
    if resolved and resolved not in full_models:
        for cand in sorted(mws_models.keys()):
            if cand in full_models:
                log.warning(
                    '[MWS] resolved id %r not in MODELS; using %r from MWS snapshot',
                    resolved,
                    cand,
                )
                resolved = cand
                break
        if resolved not in full_models:
            for cand in sorted(full_models.keys()):
                if cand in LEGACY_AUTO_IDS:
                    continue
                log.warning(
                    '[MWS] resolved id %r not in MODELS; using first non-Auto id %r',
                    resolved,
                    cand,
                )
                resolved = cand
                break

    if not resolved:
        log.error('[MWS] could not resolve Auto to any model')
        raise ValueError(
            'MWS Auto could not pick a model. Ensure MWS /models lists team models or set MWS_GPT_DEFAULT_TEXT_MODEL.'
        )

    wf = build_auto_workflow(
        decision={
            **decision,
            'model_id': resolved,
        },
        available=set(mws_models.keys()),
        config=config,
        message_text=text,
        attachments=att,
        params=form_data.get('params') or {},
    )
    rd = decision.get('routing_decision') or {}
    meta = {
        'resolved_model_id': resolved,
        'reason': decision.get('reason'),
        'modality': decision.get('modality'),
        'warnings': list(decision.get('warnings') or []),
        'original_requested_id': mid,
        'routing_decision': rd,
        'orchestration': {
            'mode': 'auto',
            'complexity': decision.get('complexity'),
            'complexity_reason': decision.get('complexity_reason'),
            'workflow': wf,
        },
    }
    log.info(
        '[MWS-Router] Auto -> %s (task=%s, confidence=%.2f, reason=%s)',
        resolved,
        rd.get('primary_task', '?'),
        rd.get('confidence', 0),
        meta.get('reason'),
    )
    return resolved, meta


def _is_mws_tagged_model(model: dict[str, Any], tag: str) -> bool:
    tags = model.get('tags') or []
    for t in tags:
        if isinstance(t, dict) and t.get('name') == tag:
            return True
        if isinstance(t, str) and t == tag:
            return True
    return False
