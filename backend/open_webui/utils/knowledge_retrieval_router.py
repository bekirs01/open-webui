"""
Heuristics for when to run vector RAG on attached Knowledge / project files.

Goals:
- Skip retrieval for trivial turns (greetings, thanks) to reduce latency.
- Run retrieval when the user clearly refers to documents, workspace, or project context.
- Prefer memory-related phrasing to avoid polluting answers with unrelated KB chunks (hinted in chat_assistant_hints).
"""

from __future__ import annotations

import os
import re
from typing import Any

# --- Simple / social messages (no document intent) ---------------------------------

_SIMPLE_EN = re.compile(
    r'^\s*(hi|hello|hey|yo|sup|thanks|thank\s+you|thx|ty|ok|okay|k\b|yes|no|yep|nope|bye|goodbye|'
    r'good\s+morning|good\s+afternoon|good\s+evening|gm\b|gn\b|lol|haha|ha\s+ha)\b[\s!.,?]*$',
    re.I,
)

_SIMPLE_AR = re.compile(
    r'^\s*(مرحبا|أهلا|السلام\s*عليكم|شكرا|شكراً|تمام|حسنا|نعم|لا|مع\s*السلامة)\b[\s!.,?]*$',
)

_SIMPLE_RU = re.compile(
    r'^\s*(привет|здравствуй(те)?|спасибо|ок(ей)?|да|нет|пока|доброе\s+(утро|день|вечер))\b[\s!.,?]*$',
    re.I,
)


# --- Strong signals to search attached knowledge / project files --------------------

_DOC_SIGNAL_EN = re.compile(
    r'\b('
    r'file|files|document|documents|pdf|attachment|attachments|upload|uploaded|'
    r'knowledge|kb\b|handbook|manual|readme|spec|specification|policy|policies|'
    r'workspace|project|folder|repository|repo\b|codebase|snippet|section|chapter|page|'
    r'according\s+to|per\s+the|in\s+the\s+doc|from\s+the\s+doc|cite|citation|source|'
    r'what\s+does\s+it\s+say|summarize\s+(the|this|our)|extract\s+from|'
    r'quote|verbatim|context\s+above|above\s+text|this\s+paper|the\s+paper'
    r')\b',
    re.I,
)

_DOC_SIGNAL_RU = re.compile(
    r'(документ|файл|вложен|база\s+знаний|политик|спецификац|руководств|раздел|цитат|'
    r'согласно|в\s+проекте|репозитор|кодов(ая|ой)\s+баз)',
    re.I,
)

_DOC_SIGNAL_AR = re.compile(
    r'(ملف|مستند|مرفق|مشروع|سياسة|دليل|قسم|اقتباس|وفق|ما\s*هو\s*رأي\s*الوثيقة)',
)

_MEMORY_FIRST = re.compile(
    r'\b('
    r'what\s+did\s+i\s+say|what\s+was\s+my|do\s+you\s+remember|'
    r'remind\s+me|earlier\s+i|last\s+time|yesterday\s+i|'
    r'my\s+preference|you\s+said\s+before|our\s+last\s+chat'
    r')\b',
    re.I,
)

# Russian: "помнишь", "что я говорил", "напомни"
_MEMORY_FIRST_RU = re.compile(
    r'(помнишь|помните|что\s+я\s+говорил|что\s+я\s+сказал|напомни|в\s+прошлый\s+раз)',
    re.I,
)

# Arabic: e.g. "do you remember" / "remember" (ASCII-safe source file)
_MEMORY_FIRST_AR = re.compile(
    r'(\u0647\u0644\s+\u062a\u062a\u0630\u0643\u0631|\u0645\u0627\s+\u0642\u0644\u062a|\u062a\u0630\u0643\u0631)',
)


def selective_rag_enabled() -> bool:
    return (os.environ.get('CHAT_SELECTIVE_RAG_ENABLED', 'true') or 'true').lower() == 'true'


def is_memory_preferred_message(text: str | None) -> bool:
    if not text or not str(text).strip():
        return False
    s = str(text).strip()
    return bool(_MEMORY_FIRST.search(s) or _MEMORY_FIRST_RU.search(s) or _MEMORY_FIRST_AR.search(s))


def is_simple_social_message(text: str | None) -> bool:
    if not text or not str(text).strip():
        return False
    s = str(text).strip()
    if len(s) > 120:
        return False
    return bool(_SIMPLE_EN.match(s) or _SIMPLE_AR.match(s) or _SIMPLE_RU.match(s))


def signals_knowledge_or_project_query(text: str | None) -> bool:
    if not text or not str(text).strip():
        return False
    s = str(text).strip()
    if _DOC_SIGNAL_EN.search(s) or _DOC_SIGNAL_RU.search(s) or _DOC_SIGNAL_AR.search(s):
        return True
    # Longer substantive questions often benefit from KB when one is attached
    if len(s) > 220:
        return True
    return False


def should_skip_retrieval_for_message(text: str | None) -> bool:
    if not selective_rag_enabled():
        return False
    if is_memory_preferred_message(text):
        return True
    if is_simple_social_message(text) and not signals_knowledge_or_project_query(text):
        return True
    return False


def _item_triggers_vector_rag(item: dict[str, Any]) -> bool:
    """Whether this file item may trigger embedding / vector lookup (expensive path)."""
    if not item or not isinstance(item, dict):
        return False
    if item.get('context') == 'full' or item.get('docs'):
        # Full context still reads storage; skip only when should_skip_retrieval_for_message
        return True
    t = item.get('type', 'file')
    if t in ('collection', 'note', 'chat', 'url', 'text'):
        return True
    if t == 'file':
        return True
    if item.get('collection_name') or item.get('collection_names'):
        return True
    return False


def filter_files_for_retrieval(files: list[dict[str, Any]] | None, user_message: str | None) -> list[dict[str, Any]]:
    """
    Remove file/collection items that would trigger RAG when the message is trivial
    and does not ask about documents or workspace context.
    """
    if not files:
        return files or []
    if not should_skip_retrieval_for_message(user_message):
        return files

    kept: list[dict[str, Any]] = []
    for item in files:
        if _item_triggers_vector_rag(item):
            continue
        kept.append(item)
    return kept


def should_include_model_knowledge_files(user_message: str | None) -> bool:
    """Whether to merge model-attached Knowledge collections into the RAG file list."""
    if not selective_rag_enabled():
        return True
    if is_memory_preferred_message(user_message):
        return False
    if is_simple_social_message(user_message) and not signals_knowledge_or_project_query(user_message):
        return False
    return True
