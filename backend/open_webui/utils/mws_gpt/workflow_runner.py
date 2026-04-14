"""
Runs internal non-stream MWS steps before the main chat completion (Auto orchestration).

Full-history mode: the second (user-facing) model receives the COMPLETE conversation
history — including images, long-term memory injections, RAG context, and cross-chat
snapshots — plus the first model's draft as an additional assistant message and a
concise synthesis directive.  This eliminates the context-loss problem where the
polisher/synthesizer/reviewer had no access to prior turns.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

log = logging.getLogger(__name__)

_SYNTHESIS_ROLE_NOTE = (
    'An earlier AI model produced the draft answer above. '
    'You are the final editor. Produce ONE polished, complete answer in the same language '
    'as the user. Preserve images, code blocks, and factual claims from earlier context. '
    'Do not mix scripts or paste raw foreign text. Improve clarity, structure, and '
    'completeness; remove redundancy.'
)


def _extract_assistant_text(resp: Any) -> str:
    if resp is None:
        return ''
    if isinstance(resp, dict):
        choices = resp.get('choices') or []
        if not choices:
            return ''
        msg = choices[0].get('message') or {}
        return (msg.get('content') or '').strip()
    return ''


def _append_preflight_context(
    messages: list[dict[str, Any]],
    draft_text: str,
    synthesis_system: str,
    extra_instruction: str = '',
) -> list[dict[str, Any]]:
    """Return *new* message list = full history + draft assistant + synthesis directive."""
    out = copy.deepcopy(messages)

    out.append({
        'role': 'assistant',
        'content': draft_text,
    })

    directive = synthesis_system.strip()
    if extra_instruction:
        directive += '\n\n' + extra_instruction.strip()
    directive += '\n\n' + _SYNTHESIS_ROLE_NOTE

    out.append({
        'role': 'user',
        'content': directive,
    })
    return out


async def apply_mws_auto_workflow_preflight(
    request: Any,
    form_data: dict[str, Any],
    user: Any,
    metadata: dict[str, Any],
    model: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Auto-only: optional vision->text or code->review using an internal blocking completion,
    then switch form_data.model for the user-visible (usually streaming) completion.

    The second model now receives the FULL conversation history (including memory, RAG,
    cross-chat context, images) plus the first model's draft as an extra assistant turn.
    """
    try:
        from open_webui.utils.mws_gpt.active import is_mws_gpt_active
        from open_webui.utils.mws_gpt.auto_workflow import AUTO_FINAL_SYNTHESIS_SYSTEM

        if not is_mws_gpt_active(request.app.state.config):
            return form_data, model

        if metadata.get('params', {}).get('function_calling') == 'native':
            return form_data, model

        if form_data.get('_mws_auto_preflight_done'):
            return form_data, model

        if form_data.get('_mws_export_completion'):
            return form_data, model

        if (
            form_data.get('_mws_pure_draw_intent')
            or form_data.get('_mws_image_pipeline')
            or form_data.get('_mws_whisper_pipeline')
        ):
            return form_data, model

        routing = getattr(request.state, 'mws_routing', None) or {}
        orch = routing.get('orchestration') or {}
        wf = orch.get('workflow') or {}
        kind = wf.get('kind', 'single')
        if kind == 'single':
            return form_data, model

        from open_webui.routers.openai import generate_chat_completion as openai_generate_chat_completion

        deep = bool(form_data.get('mws_deep_thinking'))
        current_messages = form_data.get('messages') or []

        async def _run_block(mid: str, msgs: list) -> str:
            inner: dict[str, Any] = {
                'model': mid,
                'messages': msgs,
                'stream': False,
                'metadata': metadata,
            }
            resp = await openai_generate_chat_completion(request, inner, user)
            return _extract_assistant_text(resp)

        if kind == 'vision_then_text':
            vid = wf.get('vision_model_id')
            sid = wf.get('synthesizer_model_id')
            if not vid or not sid:
                return form_data, model
            try:
                vision_out = await _run_block(vid, current_messages)
                if not vision_out:
                    log.warning('[MWS] vision preflight empty; keeping original model')
                    return form_data, model

                extra = (
                    'The assistant message above is a visual analysis by a vision model. '
                    'Synthesize it with the full conversation into one coherent answer.'
                )
                form_data['messages'] = _append_preflight_context(
                    current_messages, vision_out, AUTO_FINAL_SYNTHESIS_SYSTEM, extra,
                )
                form_data['model'] = sid
                form_data['_mws_auto_preflight_done'] = True
                model = request.app.state.MODELS.get(sid) or model
                log.info('[MWS] auto workflow vision_then_text -> synthesizer=%s', sid)
            except Exception as e:
                log.warning('[MWS] vision_then_text failed: %s', e)

            return form_data, model

        if kind == 'text_then_polish':
            did = wf.get('drafter_model_id')
            pid = wf.get('polisher_model_id')
            if not did or not pid:
                return form_data, model
            try:
                draft = await _run_block(did, current_messages)
                if not draft:
                    return form_data, model

                if deep:
                    extra = (
                        'The assistant message above is a draft that may rely on retrieved web or '
                        'document context already present in the conversation. '
                        'Preserve factual claims supported by that context; do not invent facts. '
                        'Improve structure, clarity, and completeness; remove redundancy and repetition.'
                    )
                else:
                    extra = (
                        'Rewrite the draft above into one excellent final answer. '
                        'Be precise, well-structured, and complete. Remove redundancy.'
                    )

                form_data['messages'] = _append_preflight_context(
                    current_messages, draft, AUTO_FINAL_SYNTHESIS_SYSTEM, extra,
                )
                form_data['model'] = pid
                form_data['_mws_auto_preflight_done'] = True
                model = request.app.state.MODELS.get(pid) or model
                log.info('[MWS] auto workflow text_then_polish -> polisher=%s', pid)
            except Exception as e:
                log.warning('[MWS] text_then_polish failed: %s', e)

            return form_data, model

        if kind == 'code_then_review':
            cid = wf.get('code_model_id')
            rid = wf.get('reviewer_model_id')
            if not cid or not rid:
                return form_data, model
            try:
                draft = await _run_block(cid, current_messages)
                if not draft:
                    return form_data, model

                extra = (
                    'The assistant message above is a code draft. '
                    'If code was requested, output clean final code with brief explanation only if needed.'
                )
                form_data['messages'] = _append_preflight_context(
                    current_messages, draft, AUTO_FINAL_SYNTHESIS_SYSTEM, extra,
                )
                form_data['model'] = rid
                form_data['_mws_auto_preflight_done'] = True
                model = request.app.state.MODELS.get(rid) or model
                log.info('[MWS] auto workflow code_then_review -> reviewer=%s', rid)
            except Exception as e:
                log.warning('[MWS] code_then_review failed: %s', e)

            return form_data, model

    except Exception as e:
        log.warning('[MWS] apply_mws_auto_workflow_preflight: %s', e)

    return form_data, model
