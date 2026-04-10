"""
Merge MWS GPT OpenAI-compatible connection into global OpenAI API URL/key lists at startup.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from open_webui.utils.mws_gpt.active import is_mws_gpt_active

if TYPE_CHECKING:
    from fastapi import FastAPI

log = logging.getLogger(__name__)


def merge_mws_gpt_openai_connection(app: 'FastAPI') -> None:
    cfg = app.state.config
    if not is_mws_gpt_active(cfg):
        return

    base = (getattr(cfg, 'MWS_GPT_API_BASE_URL', None) or '').strip().rstrip('/')
    key = getattr(cfg, 'MWS_GPT_API_KEY', None) or ''
    if not base:
        log.warning('MWS GPT is active but MWS_GPT_API_BASE_URL is empty; skipping merge.')
        return
    if not key.strip():
        log.warning('MWS GPT is active but MWS_GPT_API_KEY is empty; requests will fail until set.')

    urls = list(cfg.OPENAI_API_BASE_URLS)
    keys = list(cfg.OPENAI_API_KEYS)

    # Avoid duplicate base URL
    if base in urls:
        idx = urls.index(base)
        log.info('MWS GPT: base URL already present at index %s; updating key and config.', idx)
        keys[idx] = key
        cfg.OPENAI_API_KEYS = keys
    else:
        urls.append(base)
        keys.append(key)
        cfg.OPENAI_API_BASE_URLS = urls
        cfg.OPENAI_API_KEYS = keys
        idx = len(urls) - 1

    tag = (getattr(cfg, 'MWS_GPT_TAG', None) or 'mws').strip() or 'mws'
    configs = dict(cfg.OPENAI_API_CONFIGS or {})
    entry = {
        'enable': True,
        'connection_type': 'external',
        'tags': [{'name': tag}],
    }
    configs[str(idx)] = {**configs.get(str(idx), {}), **entry}
    # Legacy key by URL
    configs[base] = {**configs.get(base, {}), **entry}
    cfg.OPENAI_API_CONFIGS = configs

    if not cfg.ENABLE_OPENAI_API:
        cfg.ENABLE_OPENAI_API = True
        log.info('MWS GPT: ENABLE_OPENAI_API enabled.')

    # Görsel üretimi (/v1/images/generations) ayrı config kullanır; MWS ile aynı uç noktayı senkronize et.
    cfg.IMAGES_OPENAI_API_BASE_URL = base
    cfg.IMAGES_OPENAI_API_KEY = key.strip()
    if getattr(cfg, 'IMAGE_GENERATION_ENGINE', None) in (None, '', 'openai'):
        cfg.IMAGE_GENERATION_ENGINE = 'openai'
    cfg.ENABLE_IMAGE_GENERATION = True
    img_default = (getattr(cfg, 'MWS_GPT_DEFAULT_IMAGE_MODEL', None) or '').strip()
    if img_default:
        cfg.IMAGE_GENERATION_MODEL = img_default
    log.info('MWS GPT: IMAGES_OPENAI_* ve görsel motoru OpenAI uyumlu MWS ile hizalandı.')

    # Web araması: motor boşsa duckduckgo (API anahtarı gerekmez). TAVILY vb. için env veya Admin.
    if os.environ.get('MWS_ENABLE_WEB_SEARCH', 'true').lower() == 'true':
        if not getattr(cfg, 'ENABLE_WEB_SEARCH', False):
            cfg.ENABLE_WEB_SEARCH = True
            log.info('MWS GPT: ENABLE_WEB_SEARCH açıldı (MWS_ENABLE_WEB_SEARCH=false ile kapatılabilir).')
        override = os.environ.get('MWS_WEB_SEARCH_ENGINE', '').strip()
        current = (getattr(cfg, 'WEB_SEARCH_ENGINE', None) or '').strip()
        if override:
            cfg.WEB_SEARCH_ENGINE = override
            log.info('MWS GPT: WEB_SEARCH_ENGINE=%s (MWS_WEB_SEARCH_ENGINE)', override)
        elif not current:
            cfg.WEB_SEARCH_ENGINE = 'duckduckgo'
            log.info(
                'MWS GPT: WEB_SEARCH_ENGINE=duckduckgo (anahtarsız; Tavily için WEB_SEARCH_ENGINE=tavily + TAVILY_API_KEY)'
            )

    log.info(
        'MWS GPT: merged OpenAI-compatible endpoint at index %s (tag=%s).',
        idx,
        tag,
    )
