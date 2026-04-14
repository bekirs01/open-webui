"""Image-generation safety gate (server-side policy before routing to image models)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SafetyGateResult:
    allowed: bool
    reason_code: str | None = None


def evaluate_image_generation_safety(routing_text: str) -> SafetyGateResult:
    """
    Returns whether Auto may route to image_generation for this normalized text.
    Default: allow; tighten via env / config in a follow-up if needed.
    """
    _ = routing_text
    return SafetyGateResult(allowed=True, reason_code=None)
