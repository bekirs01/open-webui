"""
MWS GPT auto-router and request resolution.
"""

from __future__ import annotations

import logging
from typing import Any

from open_webui.utils.mws_gpt.registry import (
    Capability,
    build_mws_registry,
    classify_task_modality,
    collect_attachment_kinds,
    extract_last_user_text,
    pick_fallback_model_id,
)

log = logging.getLogger(__name__)


def _env_defaults_from_config(config: Any) -> dict[str, str | None]:
    def g(name: str) -> str | None:
        if not hasattr(config, name):
            return None
        v = getattr(config, name)
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    return {
        'text': g('MWS_GPT_DEFAULT_TEXT_MODEL'),
        'code': g('MWS_GPT_DEFAULT_CODE_MODEL'),
        'vision': g('MWS_GPT_DEFAULT_VISION_MODEL'),
        'image_generation': g('MWS_GPT_DEFAULT_IMAGE_MODEL'),
        'audio_transcription': g('MWS_GPT_DEFAULT_AUDIO_MODEL'),
        'embedding': g('MWS_GPT_DEFAULT_EMBEDDING_MODEL'),
    }


def decide_mws_model(
    *,
    manual_model_id: str | None,
    message_text: str,
    attachments: set[str],
    input_mode: str | None,
    openai_models: dict[str, dict[str, Any]],
    config: Any,
) -> dict[str, Any]:
    """
    Core auto-router. If manual_model_id is set and not the sentinel 'mws:auto',
    returns that id with reason 'manual_override'.

    openai_models: request.app.state.OPENAI_MODELS (id -> model dict with urlIdx, tags, ...).
    """
    if manual_model_id and manual_model_id != 'mws:auto':
        return {
            'model_id': manual_model_id,
            'reason': 'manual_override',
            'modality': None,
            'warnings': [],
        }

    fetched = list(openai_models.values()) if openai_models else []
    env_defaults = _env_defaults_from_config(config)
    records, reg_warnings = build_mws_registry(fetched, {k: env_defaults.get(k) for k in env_defaults})

    if not getattr(config, 'MWS_GPT_AUTO_ROUTING', None) or not config.MWS_GPT_AUTO_ROUTING:
        fid, w = pick_fallback_model_id(
            records,
            {k: env_defaults.get(k) for k in env_defaults},
            'text',
        )
        warnings = list(reg_warnings)
        if w:
            warnings.append(w)
        log.info(
            '[MWS] auto-routing disabled; using text default model=%s warnings=%s',
            fid,
            warnings,
        )
        return {
            'model_id': fid,
            'reason': 'auto_disabled_use_text_default',
            'modality': 'text',
            'warnings': warnings,
        }

    modality, mod_reason = classify_task_modality(
        message_text=message_text,
        attachments=attachments,
        input_mode=input_mode,
    )

    target: Capability = modality
    # Map image_generation to image model env
    pick, w = pick_fallback_model_id(
        records,
        {k: env_defaults.get(k) for k in env_defaults},
        target,
    )
    warnings = list(reg_warnings)
    if w:
        warnings.append(w)
    if not pick:
        pick, w2 = pick_fallback_model_id(
            records,
            {k: env_defaults.get(k) for k in env_defaults},
            'text',
        )
        if w2:
            warnings.append(w2)
        log.warning('[MWS] no model for %s; fell back to text: %s', target, pick)

    log.info(
        '[MWS] auto-route modality=%s (%s) -> model=%s warnings=%s',
        target,
        mod_reason,
        pick,
        warnings,
    )

    return {
        'model_id': pick,
        'reason': f'auto:{mod_reason}',
        'modality': target,
        'warnings': warnings,
    }


MWS_AUTO_ID = 'mws:auto'


def resolve_mws_chat_model(
    request: Any,
    form_data: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    """
    Replace mws:auto with a concrete OpenAI-model id. Returns (new_model_id, routing_meta_or_none).
    """
    from open_webui.utils.mws_gpt.active import is_mws_gpt_active

    config = request.app.state.config
    if not is_mws_gpt_active(config):
        return form_data.get('model') or '', None

    mid = form_data.get('model') or ''
    if mid != MWS_AUTO_ID:
        return mid, None

    models = request.app.state.OPENAI_MODELS or {}
    # Only route models that belong to MWS connection (tag 'mws' on connection)
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
    )

    resolved = decision.get('model_id')
    if not resolved:
        log.error('[MWS] auto-router returned empty model_id')
        raise ValueError('MWS GPT: could not resolve a model for Auto mode. Check MWS env defaults and /models.')

    meta = {
        'resolved_model_id': resolved,
        'reason': decision.get('reason'),
        'modality': decision.get('modality'),
        'warnings': decision.get('warnings') or [],
        'original_requested_id': mid,
    }
    log.info('[MWS] resolved auto -> %s (%s)', resolved, meta.get('reason'))
    return resolved, meta


def _is_mws_tagged_model(model: dict[str, Any], tag: str) -> bool:
    tags = model.get('tags') or []
    for t in tags:
        if isinstance(t, dict) and t.get('name') == tag:
            return True
        if isinstance(t, str) and t == tag:
            return True
    return False
