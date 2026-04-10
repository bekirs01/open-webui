"""Detect whether MWS GPT integration should be active (UI + routing)."""

from __future__ import annotations

from typing import Any


def is_mws_gpt_active(config: Any) -> bool:
    """
    True if MWS is explicitly enabled OR both API base URL and API key are set in config.
    This avoids an empty model list when users configure URL+key but forget MWS_GPT_ENABLED.
    """
    if getattr(config, 'MWS_GPT_ENABLED', None) and config.MWS_GPT_ENABLED:
        return True
    base = (getattr(config, 'MWS_GPT_API_BASE_URL', None) or '').strip()
    key = (getattr(config, 'MWS_GPT_API_KEY', None) or '').strip()
    return bool(base and key)
