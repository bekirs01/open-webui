"""Ordered fallback chains per modality (same family first)."""

from __future__ import annotations

from open_webui.utils.mws_gpt.team_registry import (
    AUTO_AUDIO_ORDER,
    AUTO_CODE_ORDER,
    AUTO_IMAGE_ORDER,
    AUTO_TEXT_ORDER,
    AUTO_VISION_ORDER,
    MODEL_CAPABILITIES,
)


def build_fallback_chain(
    modality: str,
    selected: str | None,
    available: set[str],
) -> list[str]:
    """
    Alternative model IDs in preference order (excluding *selected*), intersected with *available*.
    """
    order_map: dict[str, list[str]] = {
        'image_generation': list(AUTO_IMAGE_ORDER),
        'vision': list(AUTO_VISION_ORDER),
        'code': list(AUTO_CODE_ORDER) + [x for x in AUTO_TEXT_ORDER if x not in AUTO_CODE_ORDER],
        'text': list(AUTO_TEXT_ORDER),
        'export': list(AUTO_TEXT_ORDER),
        'audio_transcription': list(AUTO_AUDIO_ORDER),
        'embedding': [],
    }
    base = order_map.get(modality, list(AUTO_TEXT_ORDER))
    seen: set[str] = set()
    out: list[str] = []
    if selected and selected in MODEL_CAPABILITIES:
        mc = MODEL_CAPABILITIES[selected]
        for fb in getattr(mc, 'fallback_candidates', ()) or ():
            if fb in available and fb != selected and fb not in seen:
                seen.add(fb)
                out.append(fb)
    for mid in base:
        if mid in available and mid != selected and mid not in seen:
            seen.add(mid)
            out.append(mid)
    return out
