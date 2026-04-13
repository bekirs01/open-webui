"""
Global assistant policy for MWS-tagged completions.

Default: full workspace prompt from workspace_system_prompt (central definition).
Legacy concise policy available when WORKSPACE_ASSISTANT_PROMPT_ENABLED=false.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from open_webui.utils.workspace_system_prompt import (
    WORKSPACE_ASSISTANT_FULL_PROMPT,
    WORKSPACE_DEEP_MODE_ADDENDUM,
    WORKSPACE_POLICY_MARKER,
    WORKSPACE_POLICY_MARKER_DEEP,
)

log = logging.getLogger(__name__)

# Legacy (fallback only)
MWS_POLICY_MARKER = '[MWS_ASSISTANT_POLICY_v1]'

MWS_ASSISTANT_POLICY_TEXT = """\
You are a capable assistant. Follow these rules strictly:
- Use exactly ONE natural language for the entire reply, matching the user's latest message (Turkish / English / Russian / etc.). Never mix languages or scripts in one answer unless the user explicitly asked for bilingual output.
- Never inject characters from writing systems the user did not use (e.g. Chinese, Japanese, Korean, Arabic, Hebrew, stray Cyrillic in a Turkish answer, or CJK in an English answer).
- When web or RAG context is in another language, paraphrase in the reply language — do not paste raw foreign snippets.
- Preserve the user’s exact spelling for names and words they wrote with language-specific letters (e.g. Turkish ç ğ ı ö ş ü); do not replace them with a different famous person’s name from search results without explaining the mismatch.
- Stay on topic: answer what the user asked; do not drift into unrelated topics.
- Be direct, useful, and concise. Avoid filler, hedging, and repetitive disclaimers.
- Do not invent precise historical dates, statistics, or quotes; if unsure, say briefly that you are uncertain.
- Do not output random code snippets, token soup, or garbled Unicode unless the user asked for code.
- Do not describe internal routing, model names, or "as an AI" meta unless asked.
- Use structure (bullets, short sections) only when it improves clarity.
- If the user asks to export or convert to PDF/PNG/JPG/etc., do not refuse when the server can perform that action; the system handles real file exports separately.
- Never claim you cannot save, convert, or export the last image or answer to PDF/PNG/JPG when the user uses short commands like "pdf yap" or "png ver"; do not recommend external tools for that unless conversion truly failed server-side.
- For drawings of real public figures, real buildings, universities, landmarks, or brands, the system may retrieve brief web context to ground the image; do not insist you must guess from memory alone when that pipeline runs.
"""

MWS_POLICY_MARKER_DEEP = '[MWS_ASSISTANT_POLICY_DEEP_v1]'

MWS_ASSISTANT_POLICY_DEEP_TEXT = """\
You are in Deep thinking mode. Follow these rules strictly:
- Use exactly ONE natural language for the entire reply, matching the user's message. Never mix languages or scripts unless the user asked for bilingual output.
- Prioritize correctness and depth over brevity: research-style answers are welcome when the question needs it.
- If the conversation includes retrieved web or document context (snippets, citations, RAG), ground your answer in that material; synthesize it in the user's language — do not paste untranslated multilingual blocks. When sources disagree, acknowledge uncertainty briefly.
- Do not invent precise dates, statistics, or quotes; if context does not support a claim, say so.
- Structure the answer clearly (sections, bullets) when it helps readability for complex topics.
- Do not describe internal routing, model names, or orchestration.
- Do not output random code or garbled text unless the user asked for code.
- If the user asks to export or convert to PDF/PNG/JPG/etc., do not refuse when the server can perform that action; the system handles real file exports separately.
"""


def _workspace_prompt_enabled() -> bool:
    return (os.environ.get('WORKSPACE_ASSISTANT_PROMPT_ENABLED', 'true') or 'true').lower() == 'true'


def _policy_markers_in_content(content: str) -> bool:
    if not isinstance(content, str):
        return False
    return any(
        m in content
        for m in (
            WORKSPACE_POLICY_MARKER,
            WORKSPACE_POLICY_MARKER_DEEP,
            MWS_POLICY_MARKER,
            MWS_POLICY_MARKER_DEEP,
        )
    )


def _strip_prior_mws_policy_messages(messages: list[dict]) -> list[dict]:
    """Remove earlier workspace/MWS policy system rows so Deep mode can replace standard policy."""
    out: list[dict] = []
    for m in messages or []:
        if m.get('role') != 'system':
            out.append(m)
            continue
        c = m.get('content')
        if isinstance(c, str) and _policy_markers_in_content(c):
            continue
        if isinstance(c, list):
            blob = ' '.join(
                (p.get('text') or '') for p in c if isinstance(p, dict) and p.get('type') in ('text', 'input_text')
            )
            if _policy_markers_in_content(blob):
                continue
        out.append(m)
    return out


def inject_mws_quality_policy(messages: list[dict] | None) -> list[dict]:
    """Prepend policy system message if missing. Mutates and returns messages."""
    if not messages:
        messages = []
    for m in messages:
        if m.get('role') != 'system':
            continue
        c = m.get('content')
        if isinstance(c, str) and (WORKSPACE_POLICY_MARKER in c or MWS_POLICY_MARKER in c):
            return messages
        if isinstance(c, list):
            for p in c:
                if isinstance(p, dict) and (WORKSPACE_POLICY_MARKER in (p.get('text') or '') or MWS_POLICY_MARKER in (p.get('text') or '')):
                    return messages
    if _workspace_prompt_enabled():
        body = WORKSPACE_ASSISTANT_FULL_PROMPT.strip()
        marker = WORKSPACE_POLICY_MARKER
    else:
        body = MWS_ASSISTANT_POLICY_TEXT.strip()
        marker = MWS_POLICY_MARKER
    policy_msg = {'role': 'system', 'content': f'{marker}\n{body}'}
    return [policy_msg, *messages]


def inject_mws_deep_quality_policy(messages: list[dict] | None) -> list[dict]:
    """Prepend deep policy; replaces standard workspace/MWS policy message if present."""
    if not messages:
        messages = []
    for m in messages:
        if m.get('role') != 'system':
            continue
        c = m.get('content')
        if isinstance(c, str) and WORKSPACE_POLICY_MARKER_DEEP in c:
            return messages
        if isinstance(c, list):
            for p in c:
                if isinstance(p, dict) and WORKSPACE_POLICY_MARKER_DEEP in (p.get('text') or ''):
                    return messages
    cleaned = _strip_prior_mws_policy_messages(messages)
    if _workspace_prompt_enabled():
        body = (WORKSPACE_ASSISTANT_FULL_PROMPT.strip() + WORKSPACE_DEEP_MODE_ADDENDUM).strip()
        marker = WORKSPACE_POLICY_MARKER_DEEP
    else:
        body = MWS_ASSISTANT_POLICY_DEEP_TEXT.strip()
        marker = MWS_POLICY_MARKER_DEEP
    policy_msg = {'role': 'system', 'content': f'{marker}\n{body}'}
    return [policy_msg, *cleaned]


def maybe_inject_mws_assistant_policy(request: Any, form_data: dict, model: dict) -> None:
    """If completion uses an MWS-tagged model, prepend assistant policy (idempotent)."""
    if (
        form_data.get('_mws_pure_draw_intent')
        or form_data.get('_mws_image_pipeline')
        or form_data.get('_mws_export_completion')
    ):
        return
    if os.environ.get('MWS_INJECT_QUALITY_POLICY', 'true').lower() != 'true':
        return
    try:
        from open_webui.utils.mws_gpt.active import is_mws_gpt_active
        from open_webui.utils.mws_gpt.router import _is_mws_tagged_model
        from open_webui.utils.mws_gpt.registry import (
            collect_attachment_kinds,
            extract_last_user_text,
            wants_image_edit_pipeline_turn,
        )
        from open_webui.utils.misc import add_or_update_system_message

        cfg = request.app.state.config
        _active = is_mws_gpt_active(cfg)
        if _active:
            lu = extract_last_user_text(form_data.get('messages') or [])
            att = collect_attachment_kinds(form_data.get('files'), form_data.get('messages'))
            if wants_image_edit_pipeline_turn(lu) and 'image' in att:
                form_data['messages'] = add_or_update_system_message(
                    '\n[IMAGE_EDIT_CONTEXT] The user attached a photo and asked to edit or restyle it. '
                    'Do not refuse, do not say you cannot edit images, and do not ask for unnecessary details '
                    'when the request is already actionable. The server performs the edit; keep your reply short.',
                    form_data.get('messages') or [],
                    append=True,
                )
        if not _active:
            return
        tag = (getattr(cfg, 'MWS_GPT_TAG', None) or 'mws').strip() or 'mws'
        if not _is_mws_tagged_model(model, tag):
            return
        if form_data.get('mws_deep_thinking'):
            form_data['messages'] = inject_mws_deep_quality_policy(form_data.get('messages') or [])
        else:
            form_data['messages'] = inject_mws_quality_policy(form_data.get('messages') or [])
    except Exception as e:
        log.debug('[MWS] assistant policy: %s', e)
