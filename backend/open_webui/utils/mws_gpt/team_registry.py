"""
MWS team allowlist, primary capability per model, and Auto routing priority chains.
IDs must match provider /v1/models when possible; normalization is case-sensitive to provider.
"""

from __future__ import annotations

import os
from typing import Any, Literal

PrimaryCap = Literal[
    'text',
    'code',
    'vision',
    'audio_transcription',
    'image_generation',
    'embedding',
]

# Exact IDs from team brief (provider must expose these for routing to succeed)
TEAM_ALLOWLIST: frozenset[str] = frozenset(
    {
        'deepseek-r1-distill-qwen-32b',
        'gpt-oss-20b',
        'cotype-pro-vl-32b',
        'llama-3.1-8b-instruct',
        'QwQ-32B',
        'qwen2.5-vl',
        'BAAI/bge-multilingual-gemma2',
        'gemma-3-27b-it',
        'qwen3-embedding-8b',
        'qwen3-vl-30b-a3b-instruct',
        'qwen2.5-72b-instruct',
        'mws-gpt-alpha',
        'qwen3-32b',
        'qwen2.5-vl-72b',
        'bge-m3',
        'gpt-oss-120b',
        'llama-3.3-70b-instruct',
        'kimi-k2-instruct',
        'Qwen3-235B-A22B-Instruct-2507-FP8',
        'whisper-medium',
        'whisper-turbo-local',
        'glm-4.6-357b',
        'qwen3-coder-480b-a35b',
        'T-pro-it-1.0',
        'qwen-image-lightning',
        'qwen-image',
    }
)

# One primary capability per model (drives routing & UI)
MODEL_PRIMARY_CAPABILITY: dict[str, PrimaryCap] = {
    'qwen-image': 'image_generation',
    'qwen-image-lightning': 'image_generation',
    'whisper-medium': 'audio_transcription',
    'whisper-turbo-local': 'audio_transcription',
    'bge-m3': 'embedding',
    'qwen3-embedding-8b': 'embedding',
    'BAAI/bge-multilingual-gemma2': 'embedding',
    'qwen3-coder-480b-a35b': 'code',
    'cotype-pro-vl-32b': 'vision',
    'qwen2.5-vl': 'vision',
    'qwen2.5-vl-72b': 'vision',
    'qwen3-vl-30b-a3b-instruct': 'vision',
    'deepseek-r1-distill-qwen-32b': 'text',
    'gpt-oss-20b': 'text',
    'llama-3.1-8b-instruct': 'text',
    'QwQ-32B': 'text',
    'gemma-3-27b-it': 'text',
    'qwen2.5-72b-instruct': 'text',
    'mws-gpt-alpha': 'text',
    'qwen3-32b': 'text',
    'gpt-oss-120b': 'text',
    'llama-3.3-70b-instruct': 'text',
    'kimi-k2-instruct': 'text',
    'Qwen3-235B-A22B-Instruct-2507-FP8': 'text',
    'glm-4.6-357b': 'text',
    'T-pro-it-1.0': 'text',
}

UI_LABEL: dict[PrimaryCap, str] = {
    'text': 'Text',
    'code': 'Code',
    'vision': 'Vision',
    'audio_transcription': 'Audio',
    'image_generation': 'Image',
    'embedding': 'Embedding',
}

AUTO_IMAGE_ORDER: list[str] = ['qwen-image', 'qwen-image-lightning']
AUTO_VISION_ORDER: list[str] = [
    'qwen3-vl-30b-a3b-instruct',
    'qwen2.5-vl-72b',
    'qwen2.5-vl',
    'cotype-pro-vl-32b',
]
AUTO_CODE_ORDER: list[str] = ['qwen3-coder-480b-a35b']
AUTO_AUDIO_ORDER: list[str] = ['whisper-turbo-local', 'whisper-medium']
AUTO_TEXT_ORDER: list[str] = [
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
AUTO_EMBEDDING_ORDER: list[str] = ['bge-m3', 'qwen3-embedding-8b', 'BAAI/bge-multilingual-gemma2']


def team_allowlist_enabled() -> bool:
    return os.environ.get('MWS_TEAM_ALLOWLIST_ONLY', 'true').lower() == 'true'


def hide_embedding_from_chat_picker() -> bool:
    return os.environ.get('MWS_HIDE_EMBEDDING_FROM_CHAT', 'true').lower() == 'true'


def get_primary_capability(model_id: str) -> PrimaryCap | None:
    if not model_id:
        return None
    if model_id in MODEL_PRIMARY_CAPABILITY:
        return MODEL_PRIMARY_CAPABILITY[model_id]
    # Sağlayıcı ID’leri tam eşleşmeyebilir (örn. önek/sonek); görsel modelleri yakala
    low = model_id.lower()
    if 'qwen-image' in low or low.endswith('image-lightning'):
        return 'image_generation'
    if any(x in low for x in ('dall-e', 'dalle', 'stable-diffusion', 'sdxl', 'flux-schnell', '/flux')):
        return 'image_generation'
    if 'whisper' in low or ('turbo-local' in low and 'whisper' in low):
        return 'audio_transcription'
    if any(
        x in low
        for x in (
            'qwen2.5-vl',
            'qwen3-vl',
            'vl-72b',
            'cotype-pro-vl',
            'llava',
        )
    ):
        return 'vision'
    if 'qwen-image' not in low and (
        'bge' in low
        or 'text-embedding' in low
        or 'qwen3-embedding' in low
        or low.endswith('embedding')
    ):
        if 'qwen2.5-vl' not in low and 'qwen3-vl' not in low and 'vl-' not in low:
            return 'embedding'
    if 'qwen3-coder' in low or 'coder-480' in low:
        return 'code'
    return None


def filter_team_available(model_ids: set[str]) -> set[str]:
    """Intersect with team allowlist when enabled."""
    if not team_allowlist_enabled():
        return set(model_ids)
    return {m for m in model_ids if m in TEAM_ALLOWLIST}


def first_available(preferred: list[str], available: set[str]) -> str | None:
    for mid in preferred:
        if mid in available:
            return mid
    return None


def pick_auto_target_model(
    modality: str,
    available: set[str],
) -> tuple[str | None, str | None]:
    """
    Pick real model ID for Auto from allowed set. Returns (model_id, warning_or_none).
    Never returns synthetic IDs.
    """
    av = filter_team_available(available)
    if not av:
        return None, 'MWS: no team-allowed models in available set.'

    if modality == 'image_generation':
        pick = first_available(AUTO_IMAGE_ORDER, av)
        if pick:
            return pick, None
        return None, 'MWS: no image model available (need qwen-image or qwen-image-lightning).'

    if modality == 'vision':
        pick = first_available(AUTO_VISION_ORDER, av)
        if pick:
            return pick, None
        return None, 'MWS: no vision model available.'

    if modality == 'code':
        pick = first_available(AUTO_CODE_ORDER, av)
        if pick:
            return pick, None
        # fallback: strong text
        pick = first_available(AUTO_TEXT_ORDER, av)
        return pick, 'MWS: code model unavailable; used text fallback.' if pick else None

    if modality == 'audio_transcription':
        # Whisper handles /audio/transcriptions only — never use it for chat completions.
        # After transcription the user message is plain text, so route to a text model.
        pick = first_available(AUTO_TEXT_ORDER, av)
        if pick:
            return pick, None
        return None, 'MWS: no text model available for audio chat.'

    if modality == 'embedding':
        # Auto must not pick embedding for chat — caller should not use this for chat reply
        return None, 'MWS: embedding not used for Auto chat.'

    if modality == 'export':
        pick = first_available(AUTO_TEXT_ORDER, av)
        if pick:
            return pick, None
        return None, 'MWS: no text model for export fallback.'

    # text default
    pick = first_available(AUTO_TEXT_ORDER, av)
    if pick:
        return pick, None
    # any text-capable left
    for mid in sorted(av):
        c = get_primary_capability(mid)
        if c == 'text':
            return mid, None
    if av:
        return next(iter(sorted(av))), 'MWS: unexpected fallback to first available model.'
    return None, None


def pick_text_model_for_chat_followup(request: Any) -> str | None:
    """
    After image generation, chat completion must not use image-only model IDs (MWS returns 404 on /chat/completions).
    Picks a text-capable model present in app.state.MODELS.
    """
    cfg = request.app.state.config
    models = getattr(request.app.state, 'MODELS', None) or {}
    candidates: list[str] = []
    for c in (
        (getattr(cfg, 'MWS_GPT_DEFAULT_TEXT_MODEL', None) or '').strip(),
        (getattr(cfg, 'TASK_MODEL', None) or '').strip(),
    ):
        if c and c not in candidates:
            candidates.append(c)
    candidates.extend(AUTO_TEXT_ORDER)
    for mid in candidates:
        if mid not in models:
            continue
        cap = get_primary_capability(mid)
        if cap in ('embedding', 'image_generation', 'audio_transcription'):
            continue
        return mid
    for mid in sorted(models.keys()):
        cap = get_primary_capability(mid)
        if cap in ('embedding', 'image_generation', 'audio_transcription'):
            continue
        m = models.get(mid) or {}
        if m.get('owned_by') == 'openai':
            return mid
    return None


def enrich_model_meta(model: dict[str, Any]) -> None:
    """Attach MWS team labels to a model dict (mutates)."""
    mid = model.get('id') or ''
    cap = get_primary_capability(mid)
    if cap is None:
        return
    info = model.setdefault('info', {})
    meta = info.setdefault('meta', {})
    meta['mws_primary_capability'] = cap
    meta['mws_ui_label'] = UI_LABEL[cap]
    meta['mws_capabilities'] = [UI_LABEL[cap]]
    meta['mws_embedding_only'] = cap == 'embedding'
    meta['mws_audio_only'] = cap == 'audio_transcription'
    meta['mws_chat_allowed'] = cap not in ('embedding', 'audio_transcription')


def validate_chat_model_selection(model_id: str, form_data: dict[str, Any]) -> tuple[bool, str | None]:
    """
    Returns (ok, error_message). Blocks embedding and audio without attachment for normal chat.
    """
    cap = get_primary_capability(model_id)
    if cap is None:
        return True, None
    if cap == 'embedding':
        return False, (
            'This model is for embeddings only, not chat. Pick a text model or Auto.'
        )
    if cap == 'audio_transcription':
        # Whisper is for /audio/transcriptions (STT), not chat/completions — even with audio attached.
        return (
            False,
            'Whisper/STT models are not for chat. Use Auto or a text model; uploaded audio is transcribed automatically.',
        )
    return True, None
