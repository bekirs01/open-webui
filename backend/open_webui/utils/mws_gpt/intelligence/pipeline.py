"""Normalize user text before deterministic routing (classifier input)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RoutingInput:
    """Output of build_routing_input — stable text + audit trail of transforms."""

    text_for_classification: str
    steps_applied: tuple[str, ...]


def build_routing_input(message_text: str, config: Any) -> RoutingInput:
    """
    Prepare text for classify_task_modality / complexity. Keeps steps small so
    routing stays predictable; extend here if you add NFC / locale fixes later.
    """
    t = (message_text or '').strip()
    steps: list[str] = ['strip']
    if not t:
        return RoutingInput(text_for_classification='', steps_applied=tuple(steps))
    # Light unicode normalize (optional — avoids duplicate keys in lexicon maps)
    try:
        import unicodedata

        n = unicodedata.normalize('NFC', t)
        if n != t:
            t = n
            steps.append('nfc')
    except Exception:
        pass
    return RoutingInput(text_for_classification=t, steps_applied=tuple(steps))
