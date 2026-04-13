"""
Tool-backed export/conversion for follow-up messages (PDF, PNG, JPG, WEBP, SVG wrap, text formats).
"""

from __future__ import annotations

import io
import json
import logging
from typing import Any

from fastapi import Request, UploadFile

log = logging.getLogger(__name__)


def _artifact_from_chat_file_rows(
    request: Request,
    chat_id: str,
    messages: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """
    Fallback when assistant message JSON has no `files` but ChatFile rows exist
    (legacy rows from insert_chat_files without add_message_files).
    """
    if not messages:
        return None
    from open_webui.models.chats import Chats
    from open_webui.models.files import Files

    tail_user: int | None = None
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get('role') == 'user':
            tail_user = i
            break
    search = messages[:tail_user] if tail_user is not None else messages

    def _is_raster_file(fm: Any) -> bool:
        meta = getattr(fm, 'meta', None) or {}
        data = getattr(fm, 'data', None) or {}
        ct = ''
        if isinstance(meta, dict):
            ct = (meta.get('content_type') or '') or ''
        if not ct and isinstance(data, dict):
            ct = (data.get('content_type') or '') or ''
        fn = (getattr(fm, 'filename', None) or '').lower()
        if ct.startswith('image/'):
            return True
        return fn.endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'))

    for m in reversed(search):
        if m.get('role') != 'assistant':
            continue
        mid = m.get('id')
        if not mid:
            continue
        try:
            rows = Chats.get_chat_files_by_chat_id_and_message_id(chat_id, mid)
        except Exception:
            continue
        for row in reversed(rows or []):
            fid = getattr(row, 'file_id', None)
            if not fid:
                continue
            fm = Files.get_file_by_id(fid)
            if not fm or not _is_raster_file(fm):
                continue
            url = str(request.app.url_path_for('get_file_content_by_id', id=fid))
            return {'kind': 'image', 'url': url, 'file_id': fid}
    return None


async def try_mws_export_conversion(
    request: Request,
    form_data: dict[str, Any],
    user: Any,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """If this turn is an export request, perform conversion and set completion flags."""
    try:
        from open_webui.utils.mws_gpt.artifact_resolver import (
            extract_last_artifact_for_export,
            extract_last_image_artifact_for_export,
            guess_user_language_turkish,
        )
        from open_webui.utils.mws_gpt.export_intent import resolve_export_intent
        from open_webui.utils.mws_gpt.registry import extract_last_user_text

        # Conversion runs for all users (not only MWS); otherwise the LLM answers "I cannot…".
        last_user = extract_last_user_text(form_data.get('messages') or [])
        intent = resolve_export_intent(last_user)
        if not intent:
            return form_data

        chat_id = metadata.get('chat_id')
        message_id = metadata.get('message_id')
        tr = guess_user_language_turkish(last_user)

        needs_image_bytes = intent.kind in ('image_raster', 'image_pdf', 'svg_embed')

        artifact: dict[str, Any] | None = None
        if needs_image_bytes:
            artifact = form_data.get('_mws_last_image_artifact')
            if artifact is None:
                artifact = extract_last_image_artifact_for_export(form_data.get('messages') or [])
        else:
            artifact = form_data.get('_mws_last_artifact')
            if artifact is None:
                artifact = extract_last_artifact_for_export(form_data.get('messages') or [])

        if artifact is None and chat_id and not str(chat_id).startswith('local:'):
            artifact = _artifact_from_chat_file_rows(
                request, chat_id, form_data.get('messages') or []
            )

        if needs_image_bytes:
            for f in form_data.get('files') or []:
                if not isinstance(f, dict):
                    continue
                ct = (f.get('content_type') or '').lower()
                u = f.get('url') or ''
                if u and (f.get('type') == 'image' or ct.startswith('image/')):
                    artifact = {'kind': 'image', 'url': u, 'file_id': f.get('id')}
                    break

        # Çıktı yoksa veya geçici sohbet: sunucu dönüşümü yapılamaz → LLM + export_* araçları
        if artifact is None:
            form_data['_mws_export_llm_fallback'] = True
            return form_data

        if not chat_id or chat_id.startswith('local:') or not message_id:
            form_data['_mws_export_llm_fallback'] = True
            return form_data

        form_data['_mws_export_intent'] = True

        from open_webui.socket.main import get_event_emitter

        emitter = get_event_emitter(metadata)
        if emitter:
            await emitter(
                {
                    'type': 'status',
                    'data': {'description': 'Exporting', 'done': False},
                }
            )

        try:
            out_bytes, filename, content_type, kind_label = _convert(
                intent=intent,
                artifact=artifact,
                title_slug='export',
            )
        except ValueError as e:
            err = str(e)
            if emitter:
                await emitter(
                    {
                        'type': 'status',
                        'data': {'description': 'Export failed', 'done': True},
                    }
                )
            if 'no_artifact' in err or 'unknown_artifact' in err or 'unsupported_file_artifact' in err:
                form_data.pop('_mws_export_intent', None)
                form_data['_mws_export_llm_fallback'] = True
                return form_data
            _fail_message(form_data, tr, 'error', detail=err)
            return form_data
        except Exception as e:
            log.warning('[MWS] export convert failed: %s', e)
            if emitter:
                await emitter(
                    {
                        'type': 'status',
                        'data': {'description': 'Export failed', 'done': True},
                    }
                )
            _fail_message(form_data, tr, 'error', detail=str(e))
            return form_data

        from open_webui.models.chats import Chats
        from open_webui.routers.files import upload_file_handler

        uf = UploadFile(
            file=io.BytesIO(out_bytes),
            filename=filename,
            headers={'content-type': content_type},
        )
        file_item = upload_file_handler(
            request,
            file=uf,
            metadata={'chat_id': chat_id, 'message_id': message_id},
            process=False,
            user=user,
        )
        if not file_item or not getattr(file_item, 'id', None):
            _fail_message(form_data, tr, 'upload')
            return form_data

        try:
            Chats.insert_chat_files(
                chat_id=chat_id,
                message_id=message_id,
                file_ids=[file_item.id],
                user_id=user.id,
            )
        except Exception as e:
            log.debug('[MWS] insert_chat_files: %s', e)

        url = str(request.app.url_path_for('get_file_content_by_id', id=file_item.id))
        if emitter:
            await emitter(
                {
                    'type': 'status',
                    'data': {'description': 'Done', 'done': True},
                }
            )
            await emitter(
                {
                    'type': 'files',
                    'data': {
                        'files': [
                            {
                                # Raster images as type "image" so the chat shows preview + download; PDF etc. stay "file"
                                'type': 'image'
                                if (content_type or '').startswith('image/')
                                else 'file',
                                'url': url,
                                'name': filename,
                                'content_type': content_type,
                            }
                        ]
                    },
                }
            )

        form_data['_mws_export_completion'] = True
        form_data['_mws_export_assistant_content'] = _success_msg(kind_label, tr)
        form_data['features'] = {}
        return form_data

    except Exception as e:
        log.warning('[MWS] export pipeline: %s', e)
        if not form_data.get('_mws_export_completion'):
            form_data.pop('_mws_export_intent', None)
        return form_data


def _success_msg(kind: str, tr: bool) -> str:
    if kind == 'pdf':
        return 'PDF hazır.' if tr else 'PDF is ready.'
    if kind in ('png', 'jpeg', 'webp'):
        if tr:
            lab = 'PNG' if kind == 'png' else ('WEBP' if kind == 'webp' else 'JPEG')
            return f'{lab} hazır.'
        return f'Here is your {kind.upper()} file.'
    if kind == 'svg':
        return 'SVG dosyası hazır (gömülü PNG).' if tr else 'SVG is ready (embedded PNG).'
    if kind == 'json':
        return 'JSON dosyası hazır.' if tr else 'JSON file is ready.'
    if kind in ('md', 'txt'):
        return 'Dosya hazır.' if tr else 'File is ready.'
    return 'Dosya hazır.' if tr else 'File is ready.'


def _fail_message(form_data: dict[str, Any], tr: bool, reason: str, detail: str = '') -> None:
    if reason == 'no_chat':
        msg = (
            'Bu dışa aktarma için kayıtlı bir sohbet gerekir.'
            if tr
            else 'A saved chat is required for this export.'
        )
    elif reason == 'upload':
        msg = 'Dosya kaydedilemedi.' if tr else 'Could not save the file.'
    elif reason == 'no_output':
        msg = (
            'Dönüştürülecek bir çıktı yok; önce görsel veya yanıt üretin.'
            if tr
            else 'Nothing to convert yet; generate an image or reply first.'
        )
    elif reason == 'unsupported':
        msg = (
            'Bu dosya türü için otomatik PDF dönüşümü yok; görsel veya metin yanıtını deneyin.'
            if tr
            else 'Automatic conversion for this file type is not available; try an image or text reply.'
        )
    elif reason == 'error':
        msg = (
            f'Dönüştürme başarısız: {detail[:200]}'
            if tr
            else f'Conversion failed: {detail[:200]}'
        )
    else:
        msg = 'Dönüştürülecek bir çıktı bulunamadı.' if tr else 'No prior output found to convert.'
    form_data['_mws_export_completion'] = True
    form_data['_mws_export_assistant_content'] = msg
    form_data['features'] = {}


def _convert(
    *,
    intent: Any,
    artifact: dict[str, Any] | None,
    title_slug: str,
) -> tuple[bytes, str, str, str]:
    from open_webui.utils.export_formats import (
        get_image_bytes_from_source,
        image_bytes_to_pdf_bytes,
        markdown_to_pdf_bytes,
        plain_text_to_pdf_bytes,
        raster_image_bytes_to_format,
        image_bytes_to_svg_embed,
        text_to_png_bytes,
    )

    kind = intent.kind
    target = intent.target

    if not artifact:
        raise ValueError('no_artifact')

    if artifact.get('kind') == 'image':
        url = (artifact.get('url') or '').strip()
        fid = artifact.get('file_id')
        src = url or (str(fid) if fid else '')
        raw = get_image_bytes_from_source(src)
        if not raw or len(raw) < 32:
            raise ValueError('empty_image_bytes')

        # Same raster format as source: return clean re-upload without useless recompression when possible
        if kind == 'image_raster' and target in ('png', 'jpeg', 'jpg', 'webp'):
            import io

            from PIL import Image as PILImage

            im = PILImage.open(io.BytesIO(raw))
            src_fmt = (im.format or 'PNG').upper()
            want = 'JPEG' if target in ('jpeg', 'jpg') else target.upper()
            if src_fmt == want or (src_fmt == 'JPEG' and target in ('jpeg', 'jpg')):
                if src_fmt == 'PNG' and want == 'PNG':
                    return raw, f'{title_slug}.png', 'image/png', 'png'
                if src_fmt in ('JPEG', 'JPG') and target in ('jpeg', 'jpg'):
                    return raw, f'{title_slug}.jpg', 'image/jpeg', 'jpeg'
                if src_fmt == 'WEBP' and want == 'WEBP':
                    return raw, f'{title_slug}.webp', 'image/webp', 'webp'

        if kind == 'image_pdf' or target == 'pdf':
            pdf = image_bytes_to_pdf_bytes(raw)
            if not pdf or len(pdf) < 200:
                raise ValueError('empty_pdf_output')
            return pdf, f'{title_slug}.pdf', 'application/pdf', 'pdf'

        if intent.kind == 'svg_embed' or target == 'svg':
            svg = image_bytes_to_svg_embed(raw, title=title_slug)
            data = svg.encode('utf-8')
            return data, f'{title_slug}.svg', 'image/svg+xml', 'svg'

        fmt = 'PNG'
        if target in ('jpeg', 'jpg'):
            fmt = 'JPEG'
        elif target == 'webp':
            fmt = 'WEBP'
        elif target == 'png':
            fmt = 'PNG'
        out, ct = raster_image_bytes_to_format(raw, fmt)
        ext = '.jpg' if 'jpeg' in ct else ('.webp' if 'webp' in ct else '.png')
        label = 'jpeg' if 'jpeg' in ct else ('webp' if 'webp' in ct else 'png')
        return out, f'{title_slug}{ext}', ct, label

    if artifact.get('kind') == 'text':
        text = artifact.get('text') or ''
        if kind == 'text_json' or target == 'json':
            payload = json.dumps({'text': text}, ensure_ascii=False, indent=2)
            data = payload.encode('utf-8')
            return data, f'{title_slug}.json', 'application/json', 'json'
        if kind == 'text_markdown' or target == 'md':
            data = text.encode('utf-8')
            return data, f'{title_slug}.md', 'text/markdown', 'md'
        if kind == 'text_plain' or target == 'txt':
            data = text.encode('utf-8')
            return data, f'{title_slug}.txt', 'text/plain', 'txt'

        if kind == 'image_raster' or target in ('png', 'jpeg', 'jpg', 'webp'):
            png = text_to_png_bytes(title_slug, text)
            if target in ('jpeg', 'jpg'):
                out, ct = raster_image_bytes_to_format(png, 'JPEG')
                return out, f'{title_slug}.jpg', ct, 'jpeg'
            if target == 'webp':
                out, ct = raster_image_bytes_to_format(png, 'WEBP')
                return out, f'{title_slug}.webp', ct, 'webp'
            return png, f'{title_slug}.png', 'image/png', 'png'

        if '```' in text or text.strip().startswith('#'):
            pdf = markdown_to_pdf_bytes(title_slug, text)
        else:
            pdf = plain_text_to_pdf_bytes(title_slug, text)
        return pdf, f'{title_slug}.pdf', 'application/pdf', 'pdf'

    if artifact.get('kind') == 'file':
        raise ValueError('unsupported_file_artifact')

    raise ValueError('unknown_artifact')
