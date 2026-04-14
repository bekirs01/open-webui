"""Policy pack id strings attached to routing metadata (logging / UI hints)."""

from __future__ import annotations


def policy_pack_for_modality(modality: str) -> str:
    if modality == 'image_generation':
        return 'image_generation_policy'
    if modality in ('vision', 'code', 'audio_transcription', 'embedding', 'export'):
        return f'{modality}_policy'
    return 'general_text_policy'
