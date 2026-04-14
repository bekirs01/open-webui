"""
Reject sensitive or low-value content before storing as long-term memory.
Extend patterns here as policy evolves.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# API keys / tokens (broad heuristics — errs on the side of blocking)
# ---------------------------------------------------------------------------
_SECRET_PATTERNS = [
    re.compile(r'\bsk-[a-zA-Z0-9]{10,}\b'),  # OpenAI-style
    re.compile(r'\bxox[baprs]-[a-zA-Z0-9-]{10,}\b'),  # Slack
    re.compile(r'\bAKIA[0-9A-Z]{16}\b'),  # AWS key id
    re.compile(r'\b(?:password|passwd|pwd|parola|sifre|şifre)\s*[:=]\s*\S+', re.I),
    re.compile(r'\bBearer\s+[a-zA-Z0-9._-]{20,}\b'),
    re.compile(r'\b(?:BEGIN (?:RSA |OPENSSH )?PRIVATE KEY)', re.I),
]

# ---------------------------------------------------------------------------
# Turkish-specific PII patterns
# ---------------------------------------------------------------------------
_TR_PII_PATTERNS = [
    # TCKN — 11-digit Turkish national ID
    re.compile(r'\b[1-9]\d{10}\b'),
    # Turkish IBAN — TR followed by 24 digits (with optional spaces)
    re.compile(r'\bTR\s?\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{2}\b', re.I),
    # Turkish mobile phone — +90 5xx or 05xx patterns
    re.compile(r'(?:\+90|0090|0)\s?5\d{2}\s?\d{3}\s?\d{2}\s?\d{2}\b'),
    # Generic card number — 16 digits grouped in 4s
    re.compile(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b'),
]

_SENSITIVE_KEYWORDS = (
    'credit card',
    'kredi kartı',
    'kredi karti',
    'cvv',
    'iban',
    'passport',
    'pasaport',
    'social security',
    'tc kimlik',
    'tckn',
    'kimlik numarası',
    'kimlik numarasi',
    'ehliyet',
    'vergi numarası',
    'vergi numarasi',
)


def is_likely_sensitive(text: str) -> bool:
    """Return True if text likely contains secrets or PII."""
    if not text or len(text.strip()) < 3:
        return True
    low = text.lower()
    for kw in _SENSITIVE_KEYWORDS:
        if kw in low:
            return True
    for rx in _SECRET_PATTERNS:
        if rx.search(text):
            return True
    for rx in _TR_PII_PATTERNS:
        if rx.search(text):
            return True
    return False


def normalize_for_dedupe(text: str) -> str:
    t = (text or '').strip().lower()
    t = re.sub(r'\s+', ' ', t)
    t = re.sub(r'[.!?]+$', '', t)
    return t[:500]
