"""
MWS GPT model registry: merge fetched OpenAI-compatible model IDs with capability hints.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

Capability = Literal['text', 'code', 'vision', 'image_generation', 'audio_transcription', 'embedding']


@dataclass
class MwsModelRecord:
    id: str
    label: str
    provider: str = 'mws'
    capabilities: set[str] = field(default_factory=set)
    manual_selectable: bool = True
    is_default_for: set[Capability] = field(default_factory=set)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'label': self.label,
            'provider': self.provider,
            'capabilities': sorted(self.capabilities),
            'manualSelectable': self.manual_selectable,
            'defaultFor': sorted(self.is_default_for),
        }


def _norm_id(mid: str) -> str:
    return (mid or '').strip()


def infer_capabilities_from_model_id(model_id: str) -> set[str]:
    """Conservative heuristics when the API does not expose modalities."""
    s = model_id.lower()
    caps: set[str] = {'text'}
    if any(
        x in s
        for x in (
            'whisper',
            'audio',
            'speech',
            'transcrib',
            'stt',
            'tts',
        )
    ):
        caps.add('audio_transcription')
    if any(x in s for x in ('vision', 'vl-', '4o', 'gpt-4-turbo', 'multimodal', 'moondream', 'llava')):
        caps.add('vision')
    if any(x in s for x in ('dall', 'image', 'diffusion', 'flux', 'sdxl', 'midjourney')):
        caps.add('image_generation')
    if any(x in s for x in ('embed', 'embedding', 'text-embedding')):
        caps.add('embedding')
    if any(x in s for x in ('code', 'coder', 'deepseek-coder', 'starcoder')):
        caps.add('code')
    return caps


def build_mws_registry(
    fetched_openai_models: list[dict[str, Any]],
    env_defaults: dict[str, str | None],
) -> tuple[list[MwsModelRecord], list[str]]:
    """
    Merge GET /models results with env default IDs and inferred capabilities.
    Returns (records, warnings).
    """
    warnings: list[str] = []
    by_id: dict[str, MwsModelRecord] = {}

    for m in fetched_openai_models or []:
        mid = _norm_id(m.get('id') or m.get('name') or '')
        if not mid:
            continue
        label = m.get('name') or mid
        caps = infer_capabilities_from_model_id(mid)
        by_id[mid] = MwsModelRecord(id=mid, label=label, capabilities=caps)

    for cap in (
        'text',
        'code',
        'vision',
        'image_generation',
        'audio_transcription',
        'embedding',
    ):
        raw = env_defaults.get(cap)
        if not raw:
            continue
        eid = _norm_id(raw)
        if not eid:
            continue
        if eid not in by_id:
            by_id[eid] = MwsModelRecord(
                id=eid,
                label=eid,
                capabilities=infer_capabilities_from_model_id(eid),
            )
            warnings.append(f"MWS: default model for '{cap}' ({eid}) not in remote /models list; using env fallback.")
        by_id[eid].is_default_for.add(cap)
        by_id[eid].capabilities.update(infer_capabilities_from_model_id(eid))

    # Ensure each declared default has at least text capability for UI grouping
    for rec in by_id.values():
        if not rec.capabilities:
            rec.capabilities.add('text')

    return list(by_id.values()), warnings


def pick_fallback_model_id(
    records: list[MwsModelRecord],
    env_defaults: dict[str, str | None],
    capability: Capability,
) -> tuple[str | None, str | None]:
    """Returns (model_id, warning)."""
    # Prefer explicit env default for this capability
    raw = env_defaults.get(capability)
    if raw:
        eid = _norm_id(raw)
        ids = {r.id for r in records}
        if eid and eid in ids:
            return eid, None
        if eid:
            return eid, f"MWS: default for {capability} ({eid}) not in registry; attempting anyway."
    # Any record that lists the capability
    for r in records:
        if capability in r.capabilities:
            return r.id, None
    # Plain text fallback
    for r in records:
        if 'text' in r.capabilities:
            return r.id, None
    if records:
        return records[0].id, None
    return None, f'MWS: no models available for fallback ({capability}).'


_CODE_HINT = re.compile(
    r'\b(def |class |import |async def|fn |pub fn|const |let mut|package |func |SELECT |INSERT )\b|\bSQL\b',
    re.I,
)
_IMG_INTENT = re.compile(
    r'\b(generate|draw|render|create)\b.+\b(image|picture|photo)\b|\bimage generation\b|\bdall-?e\b',
    re.I,
)


def extract_last_user_text(messages: list[dict[str, Any]] | None) -> str:
    if not messages:
        return ''
    for m in reversed(messages):
        if m.get('role') != 'user':
            continue
        c = m.get('content')
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            parts = []
            for p in c:
                if isinstance(p, dict) and p.get('type') == 'text':
                    parts.append(p.get('text') or '')
                elif isinstance(p, dict) and p.get('type') == 'input_text':
                    parts.append(p.get('text') or '')
            return '\n'.join(parts)
    return ''


def collect_attachment_kinds(
    files: list[dict[str, Any]] | None,
    messages: list[dict[str, Any]] | None,
) -> set[str]:
    kinds: set[str] = set()
    for f in files or []:
        ct = (f.get('content_type') or f.get('type') or '').lower()
        if ct.startswith('image/'):
            kinds.add('image')
        elif ct.startswith('audio/') or ct in ('audio',):
            kinds.add('audio')
    if messages:
        for m in reversed(messages[-3:]):
            c = m.get('content')
            if isinstance(c, list):
                for p in c:
                    if not isinstance(p, dict):
                        continue
                    t = p.get('type', '')
                    if t == 'image_url' or t == 'image':
                        kinds.add('image')
                    if t in ('input_audio', 'audio'):
                        kinds.add('audio')
    return kinds


def classify_task_modality(
    *,
    message_text: str,
    attachments: set[str],
    input_mode: str | None,
) -> tuple[Capability, str]:
    """
    Deterministic routing classification.
    Returns (modality, reason).
    """
    if input_mode and input_mode.lower() in ('voice', 'audio', 'call'):
        return 'audio_transcription', 'input_mode_voice_or_audio'

    if 'audio' in attachments:
        return 'audio_transcription', 'audio_attachment'
    if 'image' in attachments:
        return 'vision', 'image_attachment'

    t = message_text or ''
    if _IMG_INTENT.search(t):
        return 'image_generation', 'image_generation_intent_keywords'
    if _CODE_HINT.search(t) or '```' in t:
        return 'code', 'code_heuristic_fence_or_syntax'
    low = t.lower()
    if any(k in low for k in ('write code', 'refactor', 'unit test', 'stack trace', 'exception')):
        return 'code', 'code_intent_keywords'

    return 'text', 'default_text'
