"""
Inject MWS GPT placeholder models when /models fetch is empty or incomplete.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from open_webui.utils.mws_gpt.active import is_mws_gpt_active

log = logging.getLogger(__name__)


def _mws_url_idx(request: Any) -> int | None:
    cfg = request.app.state.config
    if not is_mws_gpt_active(cfg):
        return None
    base = (cfg.MWS_GPT_API_BASE_URL or '').strip().rstrip('/')
    if not base:
        return None
    urls = list(cfg.OPENAI_API_BASE_URLS or [])
    try:
        return urls.index(base)
    except ValueError:
        return None


def _default_ids(cfg: Any) -> list[str]:
    keys = (
        'MWS_GPT_DEFAULT_TEXT_MODEL',
        'MWS_GPT_DEFAULT_CODE_MODEL',
        'MWS_GPT_DEFAULT_VISION_MODEL',
        'MWS_GPT_DEFAULT_IMAGE_MODEL',
        'MWS_GPT_DEFAULT_AUDIO_MODEL',
        'MWS_GPT_DEFAULT_EMBEDDING_MODEL',
    )
    out: list[str] = []
    for k in keys:
        v = getattr(cfg, k, None)
        if v is None:
            continue
        s = str(v).strip()
        if s and s not in out:
            out.append(s)
    return out


def inject_mws_fallback_models(request: Any, models: list[dict[str, Any]]) -> None:
    """Mutates `models` in place."""
    cfg = request.app.state.config
    if not is_mws_gpt_active(cfg):
        return

    idx = _mws_url_idx(request)
    if idx is None:
        log.warning(
            'MWS GPT: active but base URL not found in OPENAI_API_BASE_URLS; run merge or check config.'
        )
        return

    existing = {m.get('id') for m in models if m.get('id')}

    tag_name = (getattr(cfg, 'MWS_GPT_TAG', None) or 'mws').strip() or 'mws'
    tag = {'name': tag_name}

    for mid in _default_ids(cfg):
        if mid in existing:
            continue
        models.append(
            {
                'id': mid,
                'name': mid,
                'object': 'model',
                'created': int(time.time()),
                'owned_by': 'openai',
                'openai': {'id': mid},
                'urlIdx': idx,
                'connection_type': 'external',
                'tags': [tag],
                'mws_public': True,
                'info': {
                    'meta': {
                        'description': 'MWS GPT default from environment (used when API model list is empty or incomplete).',
                        'mws_env_placeholder': True,
                    }
                },
            }
        )
        existing.add(mid)
        log.info('MWS GPT: injected env fallback model id=%s urlIdx=%s', mid, idx)

    auto_id = 'mws:auto'
    if auto_id not in existing:
        models.insert(
            0,
            {
                'id': auto_id,
                'name': 'MWS Auto',
                'object': 'model',
                'created': int(time.time()),
                'owned_by': 'openai',
                'openai': {'id': auto_id},
                'urlIdx': idx,
                'connection_type': 'external',
                'tags': [tag, {'name': 'auto'}],
                'mws_public': True,
                'info': {
                    'meta': {
                        'description': 'Automatically pick an MWS GPT model per message.',
                        'mws_auto': True,
                    }
                },
            },
        )


def sync_openai_models_cache(request: Any, models_dict: dict[str, Any]) -> None:
    """Keep OPENAI_MODELS consistent with merged MODELS for OpenAI-backed entries."""
    om: dict[str, Any] = {}
    for mid, m in models_dict.items():
        if m.get('owned_by') == 'openai':
            om[mid] = m
    request.app.state.OPENAI_MODELS = om
