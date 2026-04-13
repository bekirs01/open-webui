"""
Runs internal non-stream MWS steps before the main chat completion (Auto orchestration).
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


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


async def apply_mws_auto_workflow_preflight(
    request: Any,
    form_data: dict[str, Any],
    user: Any,
    metadata: dict[str, Any],
    model: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Auto-only: optional vision→text or code→review using an internal blocking completion,
    then switch form_data.model for the user-visible (usually streaming) completion.
    """
    try:
        from open_webui.utils.mws_gpt.active import is_mws_gpt_active
        from open_webui.utils.mws_gpt.auto_workflow import AUTO_FINAL_SYNTHESIS_SYSTEM
        from open_webui.utils.mws_gpt.registry import extract_last_user_text

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

        mini_meta = {
            k: metadata[k]
            for k in ('chat_id', 'session_id', 'message_id', 'parent_message_id')
            if k in metadata
        }
        rag_files = None
        try:
            if isinstance(metadata, dict) and metadata.get('files'):
                rag_files = metadata.get('files')
                mini_meta = {**mini_meta, 'files': rag_files}
        except Exception:
            pass

        deep = bool(form_data.get('mws_deep_thinking'))

        async def _run_block(mid: str, msgs: list) -> str:
            inner: dict[str, Any] = {
                'model': mid,
                'messages': msgs,
                'stream': False,
                'metadata': mini_meta,
            }
            resp = await openai_generate_chat_completion(request, inner, user)
            return _extract_assistant_text(resp)

        if kind == 'vision_then_text':
            vid = wf.get('vision_model_id')
            sid = wf.get('synthesizer_model_id')
            if not vid or not sid:
                return form_data, model
            try:
                vision_out = await _run_block(vid, form_data.get('messages') or [])
                if not vision_out:
                    log.warning('[MWS] vision preflight empty; keeping original model')
                    return form_data, model
                ut = extract_last_user_text(form_data.get('messages') or [])
                form_data['messages'] = [
                    {'role': 'system', 'content': AUTO_FINAL_SYNTHESIS_SYSTEM},
                    {
                        'role': 'user',
                        'content': (
                            f'User message:\n{ut}\n\n'
                            f'Visual analysis (internal):\n{vision_out}\n\n'
                            'Answer the user directly in the same language as the user message. '
                            'Do not mix scripts or paste raw foreign text. Be concise.'
                        ),
                    },
                ]
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
                draft = await _run_block(did, form_data.get('messages') or [])
                if not draft:
                    return form_data, model
                ut = extract_last_user_text(form_data.get('messages') or [])
                if deep:
                    polish_instr = (
                        'You are the final editor. The draft may rely on retrieved web or document context '
                        'already present above. Produce ONE polished answer in the same language as the user. '
                        'Do not paste raw foreign-language snippets; paraphrase in that language. '
                        'Do not mix scripts (no CJK/Arabic/etc. in Turkish/English answers unless the user used them). '
                        'Preserve factual claims that are supported by that context; do not invent facts. '
                        'Improve structure, clarity, and completeness; remove redundancy and repetition.'
                    )
                else:
                    polish_instr = (
                        'Rewrite into one excellent final answer in the same language as the user. '
                        'Single language and script only; no pasted multilingual garbage from sources. '
                        'Be precise, well-structured, and complete. Remove redundancy.'
                    )
                form_data['messages'] = [
                    {'role': 'system', 'content': AUTO_FINAL_SYNTHESIS_SYSTEM},
                    {
                        'role': 'user',
                        'content': (
                            f'User message:\n{ut}\n\n'
                            f'Draft answer (internal):\n{draft}\n\n'
                            f'{polish_instr}'
                        ),
                    },
                ]
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
                draft = await _run_block(cid, form_data.get('messages') or [])
                if not draft:
                    return form_data, model
                ut = extract_last_user_text(form_data.get('messages') or [])
                form_data['messages'] = [
                    {'role': 'system', 'content': AUTO_FINAL_SYNTHESIS_SYSTEM},
                    {
                        'role': 'user',
                        'content': (
                            f'User request:\n{ut}\n\n'
                            f'Draft solution (internal):\n{draft}\n\n'
                            'Produce the final answer in the same language as the user; single language only. '
                            'If code was requested, output clean final code with brief explanation only if needed.'
                        ),
                    },
                ]
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
