"""
MWS GPT auto-router: Auto is a mode (sentinel id `auto`), never sent upstream.
Legacy `mws:auto` is accepted and normalized to the same behavior.
"""

from __future__ import annotations

import logging
from typing import Any

from open_webui.utils.mws_gpt.registry import (
    classify_task_modality,
    collect_attachment_kinds,
    extract_last_user_text,
)
from open_webui.utils.mws_gpt.orchestrator import (
    estimate_complexity,
    orchestration_enabled,
    pick_auto_text_by_complexity,
)
from open_webui.utils.mws_gpt.auto_workflow import build_auto_workflow
from open_webui.utils.mws_gpt.team_registry import (
    TEAM_ALLOWLIST,
    filter_team_available,
    pick_auto_target_model,
    team_allowlist_enabled,
)

log = logging.getLogger(__name__)

# UI + API sentinel: never forward to provider
MWS_AUTO_ID = 'auto'
LEGACY_AUTO_IDS = frozenset({'auto', 'mws:auto'})


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
    """
    mid = (manual_model_id or '').strip()
    if mid not in LEGACY_AUTO_IDS:
        return {
            'model_id': mid or None,
            'reason': 'manual_override',
            'modality': None,
            'warnings': [],
        }

    available = _available_mws_model_ids(openai_models)
    if team_allowlist_enabled():
        available = filter_team_available(available)

    if not getattr(config, 'MWS_GPT_AUTO_ROUTING', None) or not config.MWS_GPT_AUTO_ROUTING:
        pick, w = pick_auto_target_model('text', available)
        warnings = [w] if w else []
        if not pick:
            fb = (getattr(config, 'MWS_GPT_DEFAULT_TEXT_MODEL', None) or '').strip()
            if fb and fb in available:
                pick = fb
            elif fb and (not team_allowlist_enabled() or fb in TEAM_ALLOWLIST):
                pick = fb
                warnings.append('MWS: auto-routing off; using MWS_GPT_DEFAULT_TEXT_MODEL.')
        log.info('[MWS] auto-routing disabled; model=%s warnings=%s', pick, warnings)
        return {
            'model_id': pick,
            'reason': 'auto_disabled_use_text_default',
            'modality': 'text',
            'warnings': [x for x in warnings if x],
        }

    modality, mod_reason = classify_task_modality(
        message_text=message_text,
        attachments=attachments,
        input_mode=input_mode,
    )

    px = params or {}
    deep = bool(px.get('mws_deep_thinking'))

    complexity: str | None = None
    complexity_reason: str | None = None

    if modality == 'text' and orchestration_enabled(config):
        if deep:
            complexity, complexity_reason = 'hard', 'mws_deep_thinking'
            pick, warn = pick_auto_text_by_complexity(available, 'hard')
        else:
            complexity, complexity_reason = estimate_complexity(
                message_text=message_text,
                modality=modality,
                attachments=attachments,
            )
            pick, warn = pick_auto_text_by_complexity(available, complexity)
        warnings = [warn] if warn else []
        log.info(
            '[MWS] orchestration complexity=%s (%s) -> model=%s',
            complexity,
            complexity_reason,
            pick,
        )
    elif modality == 'export' and orchestration_enabled(config):
        complexity, complexity_reason = 'simple', 'export_turn'
        pick, warn = pick_auto_text_by_complexity(available, 'simple')
        warnings = [warn] if warn else []
        log.info('[MWS] export turn -> text model=%s', pick)
    elif modality == 'code' and orchestration_enabled(config) and deep:
        complexity, complexity_reason = 'hard', 'mws_deep_thinking'
        pick, warn = pick_auto_target_model(modality, available)
        warnings = [warn] if warn else []
        log.info('[MWS] deep thinking -> code model=%s', pick)
    else:
        pick, warn = pick_auto_target_model(modality, available)
        warnings = [warn] if warn else []

    if not pick:
        # Last resort: text chain
        pick, w2 = pick_auto_target_model('text', available)
        if w2:
            warnings.append(w2)
        log.warning('[MWS] auto-route failed for %s; text fallback=%s', modality, pick)

    if not pick:
        fb = (getattr(config, 'MWS_GPT_DEFAULT_TEXT_MODEL', None) or '').strip()
        if fb:
            pick = fb
            warnings.append('MWS: used MWS_GPT_DEFAULT_TEXT_MODEL as last resort.')

    log.info(
        '[MWS] auto modality=%s (%s) -> model=%s warnings=%s',
        modality,
        mod_reason,
        pick,
        warnings,
    )

    return {
        'model_id': pick,
        'reason': f'auto:{mod_reason}',
        'modality': modality,
        'warnings': [x for x in warnings if x],
        'complexity': complexity,
        'complexity_reason': complexity_reason,
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
    if not resolved and fb:
        resolved = fb
        log.warning('[MWS] resolver empty; trying MWS_GPT_DEFAULT_TEXT_MODEL=%s', fb)

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
    meta = {
        'resolved_model_id': resolved,
        'reason': decision.get('reason'),
        'modality': decision.get('modality'),
        'warnings': list(decision.get('warnings') or []),
        'original_requested_id': mid,
        'orchestration': {
            'mode': 'auto',
            'complexity': decision.get('complexity'),
            'complexity_reason': decision.get('complexity_reason'),
            'workflow': wf,
        },
    }
    log.info('[MWS] Auto -> %s (%s)', resolved, meta.get('reason'))
    return resolved, meta


def _is_mws_tagged_model(model: dict[str, Any], tag: str) -> bool:
    tags = model.get('tags') or []
    for t in tags:
        if isinstance(t, dict) and t.get('name') == tag:
            return True
        if isinstance(t, str) and t == tag:
            return True
    return False
