"""
Fine-grained task labels for MWS Auto (debugging, metrics, tests).

*Modality* from classify_task_modality is execution-oriented; *detailed_task* is taxonomy
for explainability (primary_task string in RoutingDecision uses modality).
"""

from __future__ import annotations

import re
from typing import Literal

DetailedTask = Literal[
    'text_chat',
    'reasoning',
    'code_generation',
    'code_explanation',
    'image_generation',
    'image_understanding',
    'audio_transcription',
    'file_qa',
    'web_search',
    'web_parse',
    'translation',
    'summarization',
    'extraction',
    'memory_lookup',
    'mixed',
    'unknown',
]


_TR_SUMMARY = re.compile(
    r'\b(özet|özetle|summar|summary|tl;dr|abstract|ana\s+konu)\b',
    re.I,
)
_TR_TRANSLATION = re.compile(
    r'\b(çevir|translate|translation|ingilizce|türkçe|from\s+\w+\s+to)\b',
    re.I,
)
_CODE_EXPLAIN = re.compile(
    r'\b(explain\s+(?:this\s+)?code|what\s+does\s+this\s+code|bu\s+kodu\s+açıkla|'
    r'kodun\s+ne\s+işe\s+yaradığ|neden\s+böyle\s+çalış)\b',
    re.I,
)


def classify_detailed_task(
    *,
    modality: str,
    modality_reason: str,
    message_text: str,
    attachments: set[str],
    complexity: str | None,
) -> tuple[DetailedTask, list[str], list[str]]:
    """
    Returns (detailed_task, secondary_tasks, requires_tools).

    *requires_tools* is advisory for middleware (e.g. export pipeline, STT).
    """
    secondary: list[str] = []
    tools: list[str] = []
    t = message_text or ''
    low = t.lower()

    if modality == 'image_generation':
        return 'image_generation', secondary, tools
    if modality == 'vision':
        return 'image_understanding', secondary, tools
    if modality == 'export':
        tools.append('export_or_conversion_pipeline')
        return 'extraction', secondary, tools
    if modality == 'code':
        if _CODE_EXPLAIN.search(t):
            return 'code_explanation', secondary, tools
        return 'code_generation', secondary, tools

    if modality_reason == 'memory_or_context_question':
        return 'memory_lookup', secondary, tools

    if 'document' in attachments:
        tools.append('file_extraction_pipeline')
        if _TR_SUMMARY.search(t) or re.search(r'\b(summarize|summary|abstract)\b', low):
            return 'summarization', secondary, tools
        return 'file_qa', secondary, tools

    if 'audio' in attachments:
        tools.append('stt_pipeline')
        return 'audio_transcription', secondary, tools

    if complexity == 'hard':
        return 'reasoning', secondary, tools

    if _TR_TRANSLATION.search(t) or re.search(r'\btranslate\b', low):
        return 'translation', secondary, tools
    if _TR_SUMMARY.search(t) or re.search(r'\b(summarize|summary)\b', low):
        return 'summarization', secondary, tools

    if re.search(r'https?://\S+', t) and re.search(
        r'\b(analyze|fetch|read|parse|sayfa|page|url|link)\b',
        low,
    ):
        tools.append('url_fetch_optional')
        return 'web_parse', secondary, tools

    return 'text_chat', secondary, tools
