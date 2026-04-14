"""
MWS team allowlist, structured capability registry, and Auto routing priority chains.
IDs must match provider /v1/models when possible; normalization is case-sensitive to provider.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Literal

PrimaryCap = Literal[
    'text',
    'code',
    'vision',
    'audio_transcription',
    'image_generation',
    'embedding',
]

UICategory = Literal[
    'auto',
    'text',
    'reasoning',
    'code',
    'image_generation',
    'vision',
    'audio',
    'embedding',
]

SpeedTier = Literal['fast', 'balanced', 'slow']
QualityTier = Literal['basic', 'good', 'excellent']


@dataclass(frozen=True)
class ModelCapability:
    """Structured capability metadata for a single model."""
    id: str
    display_name: str
    primary_cap: PrimaryCap
    ui_category: UICategory
    supports_text_input: bool = True
    supports_text_output: bool = True
    supports_image_input: bool = False
    supports_image_output: bool = False
    supports_audio_input: bool = False
    supports_code: bool = False
    supports_reasoning: bool = False
    supports_streaming: bool = True
    speed_tier: SpeedTier = 'balanced'
    quality_tier: QualityTier = 'good'
    chat_allowed: bool = True
    fallback_candidates: tuple[str, ...] = ()


MODEL_CAPABILITIES: dict[str, ModelCapability] = {
    # --- Image Generation ---
    'qwen-image': ModelCapability(
        id='qwen-image', display_name='Qwen Image',
        primary_cap='image_generation', ui_category='image_generation',
        supports_text_output=False, supports_image_output=True,
        supports_streaming=False, speed_tier='slow', quality_tier='excellent',
        chat_allowed=False,
        fallback_candidates=('qwen-image-lightning',),
    ),
    'qwen-image-lightning': ModelCapability(
        id='qwen-image-lightning', display_name='Qwen Image Lightning',
        primary_cap='image_generation', ui_category='image_generation',
        supports_text_output=False, supports_image_output=True,
        supports_streaming=False, speed_tier='fast', quality_tier='good',
        chat_allowed=False,
        fallback_candidates=('qwen-image',),
    ),
    # --- Audio / ASR ---
    'whisper-medium': ModelCapability(
        id='whisper-medium', display_name='Whisper Medium',
        primary_cap='audio_transcription', ui_category='audio',
        supports_audio_input=True, supports_text_output=True,
        supports_streaming=False, speed_tier='balanced', quality_tier='good',
        chat_allowed=False,
    ),
    'whisper-turbo-local': ModelCapability(
        id='whisper-turbo-local', display_name='Whisper Turbo (Local)',
        primary_cap='audio_transcription', ui_category='audio',
        supports_audio_input=True, supports_text_output=True,
        supports_streaming=False, speed_tier='fast', quality_tier='good',
        chat_allowed=False,
    ),
    # --- Embedding ---
    'bge-m3': ModelCapability(
        id='bge-m3', display_name='BGE-M3',
        primary_cap='embedding', ui_category='embedding',
        supports_text_output=False, supports_streaming=False,
        chat_allowed=False,
    ),
    'qwen3-embedding-8b': ModelCapability(
        id='qwen3-embedding-8b', display_name='Qwen3 Embedding 8B',
        primary_cap='embedding', ui_category='embedding',
        supports_text_output=False, supports_streaming=False,
        chat_allowed=False,
    ),
    'BAAI/bge-multilingual-gemma2': ModelCapability(
        id='BAAI/bge-multilingual-gemma2', display_name='BGE Multilingual Gemma2',
        primary_cap='embedding', ui_category='embedding',
        supports_text_output=False, supports_streaming=False,
        chat_allowed=False,
    ),
    # --- Code ---
    'qwen3-coder-480b-a35b': ModelCapability(
        id='qwen3-coder-480b-a35b', display_name='Qwen3 Coder 480B',
        primary_cap='code', ui_category='code',
        supports_code=True, supports_reasoning=True,
        speed_tier='slow', quality_tier='excellent',
        fallback_candidates=('Qwen3-235B-A22B-Instruct-2507-FP8', 'deepseek-r1-distill-qwen-32b'),
    ),
    # --- Vision / VLM ---
    'qwen2.5-vl-72b': ModelCapability(
        id='qwen2.5-vl-72b', display_name='Qwen2.5 VL 72B',
        primary_cap='vision', ui_category='vision',
        supports_image_input=True, supports_code=True,
        speed_tier='balanced', quality_tier='excellent',
        fallback_candidates=('qwen3-vl-30b-a3b-instruct', 'qwen2.5-vl'),
    ),
    'qwen3-vl-30b-a3b-instruct': ModelCapability(
        id='qwen3-vl-30b-a3b-instruct', display_name='Qwen3 VL 30B',
        primary_cap='vision', ui_category='vision',
        supports_image_input=True, supports_code=True,
        speed_tier='balanced', quality_tier='good',
        fallback_candidates=('qwen2.5-vl-72b', 'qwen2.5-vl'),
    ),
    'qwen2.5-vl': ModelCapability(
        id='qwen2.5-vl', display_name='Qwen2.5 VL',
        primary_cap='vision', ui_category='vision',
        supports_image_input=True,
        speed_tier='fast', quality_tier='good',
        fallback_candidates=('qwen2.5-vl-72b', 'cotype-pro-vl-32b'),
    ),
    'cotype-pro-vl-32b': ModelCapability(
        id='cotype-pro-vl-32b', display_name='CoType Pro VL 32B',
        primary_cap='vision', ui_category='vision',
        supports_image_input=True,
        speed_tier='balanced', quality_tier='good',
        fallback_candidates=('qwen2.5-vl-72b',),
    ),
    # --- Reasoning (text models with strong reasoning) ---
    'Qwen3-235B-A22B-Instruct-2507-FP8': ModelCapability(
        id='Qwen3-235B-A22B-Instruct-2507-FP8', display_name='Qwen3 235B',
        primary_cap='text', ui_category='reasoning',
        supports_code=True, supports_reasoning=True,
        speed_tier='slow', quality_tier='excellent',
        fallback_candidates=('glm-4.6-357b', 'kimi-k2-instruct', 'gpt-oss-120b'),
    ),
    'glm-4.6-357b': ModelCapability(
        id='glm-4.6-357b', display_name='GLM 4.6 357B',
        primary_cap='text', ui_category='reasoning',
        supports_code=True, supports_reasoning=True,
        speed_tier='slow', quality_tier='excellent',
        fallback_candidates=('Qwen3-235B-A22B-Instruct-2507-FP8', 'kimi-k2-instruct'),
    ),
    'deepseek-r1-distill-qwen-32b': ModelCapability(
        id='deepseek-r1-distill-qwen-32b', display_name='DeepSeek R1 32B',
        primary_cap='text', ui_category='reasoning',
        supports_code=True, supports_reasoning=True,
        speed_tier='balanced', quality_tier='excellent',
        fallback_candidates=('QwQ-32B', 'Qwen3-235B-A22B-Instruct-2507-FP8'),
    ),
    'QwQ-32B': ModelCapability(
        id='QwQ-32B', display_name='QwQ 32B',
        primary_cap='text', ui_category='reasoning',
        supports_code=True, supports_reasoning=True,
        speed_tier='balanced', quality_tier='excellent',
        fallback_candidates=('deepseek-r1-distill-qwen-32b', 'Qwen3-235B-A22B-Instruct-2507-FP8'),
    ),
    'kimi-k2-instruct': ModelCapability(
        id='kimi-k2-instruct', display_name='Kimi K2 Instruct',
        primary_cap='text', ui_category='reasoning',
        supports_code=True, supports_reasoning=True,
        speed_tier='balanced', quality_tier='excellent',
        fallback_candidates=('glm-4.6-357b', 'Qwen3-235B-A22B-Instruct-2507-FP8'),
    ),
    # --- Text / General Chat ---
    'gpt-oss-120b': ModelCapability(
        id='gpt-oss-120b', display_name='GPT-OSS 120B',
        primary_cap='text', ui_category='text',
        supports_code=True, supports_reasoning=True,
        speed_tier='balanced', quality_tier='excellent',
        fallback_candidates=('qwen2.5-72b-instruct', 'llama-3.3-70b-instruct'),
    ),
    'qwen2.5-72b-instruct': ModelCapability(
        id='qwen2.5-72b-instruct', display_name='Qwen2.5 72B Instruct',
        primary_cap='text', ui_category='text',
        supports_code=True,
        speed_tier='balanced', quality_tier='excellent',
        fallback_candidates=('llama-3.3-70b-instruct', 'gpt-oss-120b'),
    ),
    'llama-3.3-70b-instruct': ModelCapability(
        id='llama-3.3-70b-instruct', display_name='Llama 3.3 70B',
        primary_cap='text', ui_category='text',
        supports_code=True,
        speed_tier='fast', quality_tier='good',
        fallback_candidates=('qwen2.5-72b-instruct', 'qwen3-32b'),
    ),
    'qwen3-32b': ModelCapability(
        id='qwen3-32b', display_name='Qwen3 32B',
        primary_cap='text', ui_category='text',
        supports_code=True,
        speed_tier='fast', quality_tier='good',
        fallback_candidates=('llama-3.3-70b-instruct', 'gemma-3-27b-it'),
    ),
    'mws-gpt-alpha': ModelCapability(
        id='mws-gpt-alpha', display_name='MWS GPT Alpha',
        primary_cap='text', ui_category='text',
        supports_code=True,
        speed_tier='balanced', quality_tier='good',
        fallback_candidates=('qwen3-32b', 'llama-3.3-70b-instruct'),
    ),
    'gpt-oss-20b': ModelCapability(
        id='gpt-oss-20b', display_name='GPT-OSS 20B',
        primary_cap='text', ui_category='text',
        speed_tier='fast', quality_tier='basic',
        fallback_candidates=('qwen3-32b', 'llama-3.3-70b-instruct'),
    ),
    'gemma-3-27b-it': ModelCapability(
        id='gemma-3-27b-it', display_name='Gemma 3 27B',
        primary_cap='text', ui_category='text',
        speed_tier='fast', quality_tier='good',
        fallback_candidates=('llama-3.3-70b-instruct', 'qwen3-32b'),
    ),
    'T-pro-it-1.0': ModelCapability(
        id='T-pro-it-1.0', display_name='T-Pro IT 1.0',
        primary_cap='text', ui_category='text',
        speed_tier='fast', quality_tier='basic',
        fallback_candidates=('gemma-3-27b-it', 'llama-3.3-70b-instruct'),
    ),
    'llama-3.1-8b-instruct': ModelCapability(
        id='llama-3.1-8b-instruct', display_name='Llama 3.1 8B',
        primary_cap='text', ui_category='text',
        speed_tier='fast', quality_tier='basic',
        fallback_candidates=('qwen3-32b', 'gemma-3-27b-it'),
    ),
}

# Backward compatibility: flat primary capability lookup
MODEL_PRIMARY_CAPABILITY: dict[str, PrimaryCap] = {
    mid: mc.primary_cap for mid, mc in MODEL_CAPABILITIES.items()
}

# Exact IDs from team brief (provider must expose these for routing to succeed)
TEAM_ALLOWLIST: frozenset[str] = frozenset(MODEL_CAPABILITIES.keys())

UI_LABEL: dict[PrimaryCap, str] = {
    'text': 'Text',
    'code': 'Code',
    'vision': 'Vision',
    'audio_transcription': 'Audio',
    'image_generation': 'Image',
    'embedding': 'Embedding',
}

UI_CATEGORY_LABEL: dict[UICategory, str] = {
    'auto': 'Auto',
    'text': 'Text / Chat',
    'reasoning': 'Reasoning',
    'code': 'Code',
    'image_generation': 'Image Generation',
    'vision': 'Vision',
    'audio': 'Audio / ASR',
    'embedding': 'Embedding',
}

UI_CATEGORY_SORT_KEY: dict[UICategory, str] = {
    'auto': '0',
    'reasoning': '1',
    'text': '2',
    'code': '3',
    'vision': '4',
    'image_generation': '5',
    'audio': '6',
    'embedding': '9',
}

AUTO_IMAGE_ORDER: list[str] = ['qwen-image', 'qwen-image-lightning']
AUTO_VISION_ORDER: list[str] = [
    'qwen2.5-vl-72b',
    'qwen3-vl-30b-a3b-instruct',
    'qwen2.5-vl',
    'cotype-pro-vl-32b',
]
AUTO_CODE_ORDER: list[str] = [
    'qwen3-coder-480b-a35b',
    'Qwen3-235B-A22B-Instruct-2507-FP8',
    'deepseek-r1-distill-qwen-32b',
]
# Primary quality-first for STT endpoints; fast local second
AUTO_AUDIO_ORDER: list[str] = ['whisper-medium', 'whisper-turbo-local']
# Default text fallback when orchestration picks from flat list (non-tiered paths)
AUTO_TEXT_ORDER: list[str] = [
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
# Fallback: code fallback also benefits from strong general models
AUTO_REVIEWER_ORDER: list[str] = [
    'Qwen3-235B-A22B-Instruct-2507-FP8',
    'glm-4.6-357b',
    'kimi-k2-instruct',
    'gpt-oss-120b',
    'llama-3.3-70b-instruct',
    'qwen2.5-72b-instruct',
    'qwen3-32b',
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
    *,
    available_unfiltered: set[str] | None = None,
) -> tuple[str | None, str | None]:
    """
    Pick real model ID for Auto from allowed set. Returns (model_id, warning_or_none).
    Never returns synthetic IDs.

    *available_unfiltered*: full /v1/models id set before team allowlist intersection. Used so
    image model ids that match the provider but not the exact TEAM_ALLOWLIST string (or that were
    filtered out) can still be resolved via alias / get_primary_capability.
    """
    av = filter_team_available(available)
    if not av:
        return None, 'MWS: no team-allowed models in available set.'

    if modality == 'image_generation':
        pick = first_available(AUTO_IMAGE_ORDER, av)
        if pick:
            return pick, None
        pool = available_unfiltered if available_unfiltered is not None else available
        pool = pool or set()
        # Exact team ids with different casing
        for want in AUTO_IMAGE_ORDER:
            for got in pool:
                if got == want or got.lower() == want.lower():
                    if got in av or not team_allowlist_enabled():
                        return got, None
                    return got, 'MWS: image model id matched with different casing vs team list.'
        # Any provider id that maps to image_generation (qwen-image variants, DALL-E, etc.)
        for got in sorted(pool):
            if get_primary_capability(got) == 'image_generation':
                if got in av or not team_allowlist_enabled():
                    return got, None
                return got, 'MWS: image model resolved from provider list (not in team allowlist intersection).'
        env_img = (os.environ.get('MWS_GPT_DEFAULT_IMAGE_MODEL') or '').strip()
        if env_img:
            cfg_img = env_img
            for got in sorted(pool):
                if got == cfg_img or got.lower() == cfg_img.lower():
                    return got, None
            for got in sorted(pool):
                if cfg_img in got or got.endswith(cfg_img.split('/')[-1]):
                    return got, 'MWS: image model matched via MWS_GPT_DEFAULT_IMAGE_MODEL.'
        return None, 'MWS: no image model available (set MWS_GPT_DEFAULT_IMAGE_MODEL or expose qwen-image).'

    if modality == 'vision':
        pick = first_available(AUTO_VISION_ORDER, av)
        if pick:
            return pick, None
        pool = available_unfiltered if available_unfiltered is not None else available
        pool = pool or set()
        for want in AUTO_VISION_ORDER:
            for got in pool:
                if got == want or got.lower() == want.lower():
                    if got in av or not team_allowlist_enabled():
                        return got, None
                    return got, 'MWS: vision model id matched with different casing vs team list.'
        for got in sorted(pool):
            if get_primary_capability(got) == 'vision':
                if got in av or not team_allowlist_enabled():
                    return got, None
                return got, 'MWS: vision model resolved from provider list (not in team allowlist intersection).'
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


def pick_mws_image_edit_model_id(request: Any) -> str | None:
    """
    Model id for /images/edits (MWS): prefer env, else first team image model (qwen-image, then lightning).
    """
    raw = (os.environ.get('MWS_IMAGE_EDIT_MODEL_ID') or '').strip()
    if raw:
        return raw
    models = getattr(request.app.state, 'MODELS', None) or {}
    available = set(models.keys())
    av = filter_team_available(available)
    return first_available(AUTO_IMAGE_ORDER, av)


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


def get_model_capability(model_id: str) -> ModelCapability | None:
    """Return structured capability metadata if known, else None."""
    return MODEL_CAPABILITIES.get(model_id)


def enrich_model_meta(model: dict[str, Any]) -> None:
    """Attach MWS team labels and structured capability metadata to a model dict (mutates)."""
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

    mc = MODEL_CAPABILITIES.get(mid)
    if mc:
        meta['mws_ui_category'] = mc.ui_category
        meta['mws_ui_category_label'] = UI_CATEGORY_LABEL.get(mc.ui_category, 'Other')
        meta['mws_ui_category_sort'] = UI_CATEGORY_SORT_KEY.get(mc.ui_category, '8')
        meta['mws_speed_tier'] = mc.speed_tier
        meta['mws_quality_tier'] = mc.quality_tier
        meta['mws_supports_reasoning'] = mc.supports_reasoning
        meta['mws_supports_code'] = mc.supports_code
        meta['mws_supports_image_input'] = mc.supports_image_input
        meta['mws_supports_image_output'] = mc.supports_image_output
        meta['mws_model_family'] = _infer_backend_family(mid, mc)


def _infer_backend_family(model_id: str, mc: ModelCapability) -> str:
    """Group key for frontend model picker (maps to UI_CATEGORY_LABEL)."""
    return UI_CATEGORY_LABEL.get(mc.ui_category, 'Other')


def validate_chat_model_selection(model_id: str, form_data: dict[str, Any]) -> tuple[bool, str | None]:
    """
    Returns (ok, error_message). Blocks embedding and audio without attachment for normal chat.
    """
    cap = get_primary_capability(model_id)
    if cap is None:
        return True, None
    if cap == 'embedding':
        return False, 'embedding'
    if cap == 'audio_transcription':
        return False, 'audio_transcription'
    return True, None
