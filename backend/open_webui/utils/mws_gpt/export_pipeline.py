"""
Tool-backed export/conversion for follow-up messages (PDF, PNG, JPG, WEBP, SVG wrap, text formats).
"""

from __future__ import annotations

import io
import json
import logging
import re
from typing import Any

from fastapi import Request, UploadFile

log = logging.getLogger(__name__)


def _export_file_attachment_record(
    file_item: Any,
    out_bytes: bytes,
    filename: str,
    content_type: str,
) -> dict[str, Any]:
    """
    Match builtin export tools / DB file rows. Open WebUI FileItemModal expects `id`
    (and uses url=file id) — full API paths as `url` break PDF preview and downloads.
    """
    fid = str(getattr(file_item, 'id', '') or '')
    sz = len(out_bytes or b'')
    ct = (content_type or 'application/octet-stream').strip()
    name = filename or 'export.bin'
    return {
        'type': 'file',
        'id': fid,
        'url': fid,
        'name': name,
        'size': sz,
        'content_type': ct,
        'meta': {'name': name, 'content_type': ct, 'size': sz},
    }


def _validate_export_bytes(filename: str, content_type: str, out_bytes: bytes) -> str | None:
    """Return error code or None if output looks valid."""
    if not out_bytes or len(out_bytes) < 16:
        return 'empty_bytes'
    from open_webui.utils.export_formats import _validate_pdf_magic

    fn = (filename or '').lower()
    ct = (content_type or '').lower()
    if 'pdf' in ct or fn.endswith('.pdf'):
        if not _validate_pdf_magic(out_bytes):
            return 'invalid_pdf'
    if 'jpeg' in ct or fn.endswith(('.jpg', '.jpeg')):
        if out_bytes[:3] != b'\xff\xd8\xff':
            return 'bad_image'
    if 'png' in ct or fn.endswith('.png'):
        if out_bytes[:8] != b'\x89PNG\r\n\x1a\n':
            return 'bad_image'
    return None


def _markdown_table_to_csv_bytes(text: str) -> bytes:
    """Convert markdown table or plain text lines to CSV bytes (UTF-8 BOM for Excel compat)."""
    import csv as csv_mod

    rows: list[list[str]] = []
    raw = (text or '').strip()

    if '|' in raw:
        for line in raw.split('\n'):
            line = line.strip()
            if not line:
                continue
            if line.startswith('|') and set(line.replace('|', '').strip()) <= {'-', ':', ' '}:
                continue
            cells = [c.strip() for c in line.strip('|').split('|')]
            rows.append(cells)
    elif '\t' in raw:
        for line in raw.split('\n'):
            if line.strip():
                rows.append(line.split('\t'))
    else:
        for line in raw.split('\n'):
            if line.strip():
                rows.append([line.strip()])

    if not rows:
        rows = [[raw[:500] if raw else '(empty)']]

    buf = io.StringIO()
    writer = csv_mod.writer(buf, quoting=csv_mod.QUOTE_MINIMAL)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode('utf-8-sig')


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
    # Include the current user message so files attached in the same turn are found
    search = messages[: tail_user + 1] if tail_user is not None else messages

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
        if m.get('role') not in ('assistant', 'user'):
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


def _collect_turn_files(form_data: dict[str, Any]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for src in (form_data.get('_mws_incoming_last_user_files'), form_data.get('files')):
        for f in src or []:
            if not isinstance(f, dict):
                continue
            key = str(f.get('id') or '') + '|' + str(f.get('url') or '')
            if key in seen:
                continue
            seen.add(key)
            out.append(f)

    # Also extract image_url parts from the last user message content
    # (files may have been popped and injected into content as image_url)
    if not any(_is_image_file_dict(f) for f in out):
        for m in reversed(form_data.get('messages') or []):
            if m.get('role') != 'user':
                continue
            content = m.get('content')
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get('type') == 'image_url':
                        iu = part.get('image_url') or {}
                        url = iu.get('url') if isinstance(iu, dict) else ''
                        if url:
                            key = f'|{url}'
                            if key not in seen:
                                seen.add(key)
                                out.append({'type': 'image', 'url': url, 'content_type': 'image/png'})
            break

    return out


def _is_image_file_dict(f: dict[str, Any]) -> bool:
    ct = (f.get('content_type') or '').lower()
    return f.get('type') == 'image' or ct.startswith('image/')


def _is_pdf_file_dict(f: dict[str, Any]) -> bool:
    ct = (f.get('content_type') or '').lower()
    name = (f.get('name') or f.get('filename') or '').lower()
    return ct == 'application/pdf' or name.endswith('.pdf')


def _count_turn_kinds(files: list[dict[str, Any]]) -> tuple[int, int]:
    ni = npdf = 0
    for f in files:
        if _is_image_file_dict(f):
            ni += 1
        elif _is_pdf_file_dict(f):
            npdf += 1
    return ni, npdf


def _safe_entry_name(f: dict[str, Any], idx: int, default_ext: str) -> str:
    raw = (f.get('name') or f.get('filename') or '').strip()
    if raw and re.match(r'^[^/\\]{1,160}$', raw):
        return raw
    return f'file_{idx + 1}{default_ext}'


def _bytes_from_file_dict(f: dict[str, Any], *, expect_image: bool) -> bytes:
    from open_webui.utils.export_formats import get_file_bytes_from_source, get_image_bytes_from_source

    url = (f.get('url') or '').strip()
    fid = f.get('id')
    src = url or (str(fid) if fid else '')
    if not src:
        raise ValueError('missing_file_ref')
    raw = get_image_bytes_from_source(src) if expect_image else get_file_bytes_from_source(src)
    if not raw or len(raw) < 8:
        raise ValueError('empty_bytes')
    return raw


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
        from open_webui.utils.mws_gpt.export_intent import (
            adjust_intent_for_attachment_counts,
            resolve_export_intent,
        )
        from open_webui.utils.mws_gpt.registry import extract_last_user_text

        if not user or not getattr(user, 'id', None):
            return form_data

        last_user = extract_last_user_text(form_data.get('messages') or [])
        intent = resolve_export_intent(last_user)
        if not intent:
            return form_data

        turn_files = _collect_turn_files(form_data)
        n_img, n_pdf = _count_turn_kinds(turn_files)
        intent = adjust_intent_for_attachment_counts(
            intent,
            n_images=n_img,
            n_pdfs=n_pdf,
            message_lower=last_user,
        )

        chat_id = metadata.get('chat_id')
        message_id = metadata.get('message_id')
        tr = guess_user_language_turkish(last_user)

        if intent.kind == 'conversion_unavailable':
            detail = (intent.unavailable_code or '').lower()
            if detail == 'docx':
                msg = (
                    'Word (DOCX) dosyası bu kanalda otomatik üretilemiyor. Metin olarak TXT veya PDF çıktısı isteyebilirsiniz.'
                    if tr
                    else 'DOCX export is not available here. Ask for TXT or PDF instead.'
                )
            else:
                msg = 'Bu dönüşüm şu an desteklenmiyor.' if tr else 'This conversion is not supported.'
            form_data['_mws_export_completion'] = True
            form_data['_mws_export_assistant_content'] = msg
            form_data['features'] = {}
            return form_data

        from open_webui.socket.main import get_event_emitter

        emitter = get_event_emitter(metadata)

        async def _emit_status(desc: str, done: bool) -> None:
            if emitter:
                await emitter({'type': 'status', 'data': {'description': desc, 'done': done}})

        async def _finish_success(
            out_bytes: bytes,
            filename: str,
            content_type: str,
            kind_label: str,
        ) -> dict[str, Any]:
            from open_webui.models.chats import Chats
            from open_webui.routers.files import upload_file_handler

            v_err = _validate_export_bytes(filename, content_type, out_bytes)
            if v_err:
                log.warning('[MWS] export output invalid before upload: %s', v_err)
                _fail_message(form_data, tr, 'error', detail=v_err)
                return form_data

            uf = UploadFile(
                file=io.BytesIO(out_bytes),
                filename=filename,
                headers={'content-type': content_type},
            )
            meta: dict[str, Any] = {}
            if chat_id and not str(chat_id).startswith('local:') and message_id:
                meta = {'chat_id': chat_id, 'message_id': message_id}
            file_item = upload_file_handler(
                request,
                file=uf,
                metadata=meta,
                process=False,
                user=user,
            )
            if not file_item or not getattr(file_item, 'id', None):
                _fail_message(form_data, tr, 'upload')
                return form_data

            if chat_id and not str(chat_id).startswith('local:') and message_id:
                try:
                    Chats.insert_chat_files(
                        chat_id=chat_id,
                        message_id=message_id,
                        file_ids=[file_item.id],
                        user_id=user.id,
                    )
                except Exception as e:
                    log.debug('[MWS] insert_chat_files: %s', e)

            entry = _export_file_attachment_record(file_item, out_bytes, filename, content_type)
            form_data['_mws_export_result_files'] = [entry]
            if emitter:
                await _emit_status('Done', True)
                await emitter(
                    {
                        'type': 'files',
                        'data': {'files': [entry]},
                    }
                )

            form_data['_mws_export_completion'] = True
            form_data['_mws_export_assistant_content'] = _success_msg(kind_label, tr)
            form_data['features'] = {}
            return form_data

        # --- Yapılandırılmış işlemler (yüklemeler / çoklu dosya) ---
        from open_webui.utils.export_formats import (
            build_zip_bytes,
            get_file_bytes_from_source,
            merge_pdf_bytes_list,
            multi_image_bytes_to_pdf_bytes,
            pdf_bytes_extract_text,
            pdf_bytes_split_to_zip_entries,
        )

        # Çoklu görsel → tek PDF
        if intent.kind == 'image_pdf':
            imgs = [f for f in turn_files if _is_image_file_dict(f)]
            if len(imgs) >= 2:
                try:
                    await _emit_status('Exporting', False)
                    raw_list = [_bytes_from_file_dict(f, expect_image=True) for f in imgs]
                    out_pdf = multi_image_bytes_to_pdf_bytes(raw_list)
                    return await _finish_success(out_pdf, 'export.pdf', 'application/pdf', 'pdf')
                except Exception as e:
                    log.warning('[MWS] multi image pdf: %s', e)
                    await _emit_status('Export failed', True)
                    _fail_message(form_data, tr, 'error', detail=str(e))
                    return form_data

        # ZIP (yüklemeler veya son görsel)
        if intent.kind == 'archive_zip':
            entries: list[tuple[str, bytes]] = []
            try:
                for i, f in enumerate(turn_files):
                    if _is_image_file_dict(f):
                        b = _bytes_from_file_dict(f, expect_image=True)
                        entries.append((_safe_entry_name(f, i, '.png'), b))
                    else:
                        b = _bytes_from_file_dict(f, expect_image=False)
                        ext = '.pdf' if _is_pdf_file_dict(f) else '.bin'
                        entries.append((_safe_entry_name(f, i, ext), b))
                if not entries:
                    art = form_data.get('_mws_last_image_artifact') or extract_last_image_artifact_for_export(
                        form_data.get('messages') or []
                    )
                    if art and art.get('kind') == 'image':
                        u = (art.get('url') or '').strip() or str(art.get('file_id') or '')
                        b = _bytes_from_file_dict(
                            {'url': u, 'id': art.get('file_id'), 'content_type': 'image/png'},
                            expect_image=True,
                        )
                        entries.append(('image.png', b))
                if not entries:
                    form_data['_mws_export_llm_fallback'] = True
                    return form_data
                await _emit_status('Exporting', False)
                zdata = build_zip_bytes(entries)
                return await _finish_success(zdata, 'export.zip', 'application/zip', 'zip')
            except Exception as e:
                log.warning('[MWS] zip export: %s', e)
                await _emit_status('Export failed', True)
                _fail_message(form_data, tr, 'error', detail=str(e))
                return form_data

        # PDF birleştir
        if intent.kind == 'pdf_merge':
            pdfs = [f for f in turn_files if _is_pdf_file_dict(f)]
            if len(pdfs) < 1:
                form_data['_mws_export_llm_fallback'] = True
                return form_data
            try:
                await _emit_status('Exporting', False)
                parts = [_bytes_from_file_dict(f, expect_image=False) for f in pdfs]
                merged = merge_pdf_bytes_list(parts)
                return await _finish_success(merged, 'merged.pdf', 'application/pdf', 'pdf')
            except Exception as e:
                log.warning('[MWS] pdf merge: %s', e)
                await _emit_status('Export failed', True)
                _fail_message(form_data, tr, 'error', detail=str(e))
                return form_data

        # PDF sayfa ayır → ZIP (sayfa başına PDF)
        if intent.kind == 'pdf_split_zip':
            pdf_f = next((f for f in turn_files if _is_pdf_file_dict(f)), None)
            raw_pdf: bytes | None = None
            if pdf_f:
                raw_pdf = _bytes_from_file_dict(pdf_f, expect_image=False)
            else:
                art = form_data.get('_mws_last_artifact') or extract_last_artifact_for_export(
                    form_data.get('messages') or []
                )
                if art and art.get('kind') == 'file':
                    u = (art.get('url') or '').strip() or str(art.get('file_id') or '')
                    raw_pdf = get_file_bytes_from_source(u)
            if not raw_pdf:
                form_data['_mws_export_llm_fallback'] = True
                return form_data
            try:
                await _emit_status('Exporting', False)
                page_entries = pdf_bytes_split_to_zip_entries(raw_pdf)
                zdata = build_zip_bytes(page_entries)
                return await _finish_success(zdata, 'pages.zip', 'application/zip', 'zip_pages')
            except Exception as e:
                log.warning('[MWS] pdf split: %s', e)
                await _emit_status('Export failed', True)
                _fail_message(form_data, tr, 'error', detail=str(e))
                return form_data

        # PDF → TXT
        if intent.kind == 'pdf_extract_text':
            pdf_f = next((f for f in turn_files if _is_pdf_file_dict(f)), None)
            raw_pdf: bytes | None = None
            if pdf_f:
                raw_pdf = _bytes_from_file_dict(pdf_f, expect_image=False)
            else:
                art = form_data.get('_mws_last_artifact') or extract_last_artifact_for_export(
                    form_data.get('messages') or []
                )
                if art and art.get('kind') == 'file':
                    u = (art.get('url') or '').strip() or str(art.get('file_id') or '')
                    raw_pdf = get_file_bytes_from_source(u)
            if not raw_pdf:
                form_data['_mws_export_llm_fallback'] = True
                return form_data
            try:
                await _emit_status('Exporting', False)
                text = pdf_bytes_extract_text(raw_pdf)
                data = text.encode('utf-8')
                return await _finish_success(data, 'export.txt', 'text/plain', 'txt')
            except Exception as e:
                log.warning('[MWS] pdf text: %s', e)
                await _emit_status('Export failed', True)
                _fail_message(form_data, tr, 'error', detail=str(e))
                return form_data

        # --- Tekil artifact / klasik dönüşüm ---
        needs_image_bytes = intent.kind in ('image_raster', 'image_pdf', 'svg_embed')

        artifact: dict[str, Any] | None = None

        # Priority 1: files attached in THIS turn (most reliable — not affected by DB lag)
        if needs_image_bytes:
            for f in turn_files:
                if _is_image_file_dict(f):
                    u = f.get('url') or ''
                    fid = f.get('id')
                    if u:
                        artifact = {'kind': 'image', 'url': u, 'file_id': fid}
                        break
                    if fid:
                        artifact = {'kind': 'image', 'url': str(fid), 'file_id': fid}
                        break

        # Priority 2: pre-computed artifact from messages snapshot
        if artifact is None:
            if needs_image_bytes:
                artifact = form_data.get('_mws_last_image_artifact')
                if artifact is None:
                    artifact = extract_last_image_artifact_for_export(form_data.get('messages') or [])
            else:
                artifact = form_data.get('_mws_last_artifact')
                if artifact is None:
                    artifact = extract_last_artifact_for_export(form_data.get('messages') or [])

        # Priority 3: DB chat_files rows
        if artifact is None and chat_id and not str(chat_id).startswith('local:'):
            artifact = _artifact_from_chat_file_rows(request, chat_id, form_data.get('messages') or [])

        # Priority 4: form_data top-level files
        if artifact is None:
            for f in form_data.get('files') or []:
                if not isinstance(f, dict):
                    continue
                ct = (f.get('content_type') or '').lower()
                u = f.get('url') or ''
                if u and (f.get('type') == 'image' or ct.startswith('image/')):
                    artifact = {'kind': 'image', 'url': u, 'file_id': f.get('id')}
                    break

        # Priority 5: image_url embedded in message content (after files→content injection)
        if artifact is None and needs_image_bytes:
            for m in reversed(form_data.get('messages') or []):
                if m.get('role') != 'user':
                    continue
                content = m.get('content')
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get('type') == 'image_url':
                            iu = part.get('image_url') or {}
                            u = iu.get('url') if isinstance(iu, dict) else ''
                            if u:
                                artifact = {'kind': 'image', 'url': u, 'file_id': None}
                                break
                    if artifact:
                        break

        if artifact is None:
            if needs_image_bytes:
                _fail_message(form_data, tr, 'no_source_image')
                return form_data
            form_data['_mws_export_llm_fallback'] = True
            return form_data

        form_data['_mws_export_intent'] = True

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
            if err == 'pdf_to_image_unsupported':
                _fail_message(form_data, tr, 'unsupported')
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

        v_err = _validate_export_bytes(filename, content_type, out_bytes)
        if v_err:
            log.warning('[MWS] export output invalid before upload: %s', v_err)
            if emitter:
                await emitter(
                    {
                        'type': 'status',
                        'data': {'description': 'Export failed', 'done': True},
                    }
                )
            _fail_message(form_data, tr, 'error', detail=v_err)
            return form_data

        from open_webui.models.chats import Chats
        from open_webui.routers.files import upload_file_handler

        uf = UploadFile(
            file=io.BytesIO(out_bytes),
            filename=filename,
            headers={'content-type': content_type},
        )
        meta: dict[str, Any] = {}
        if chat_id and not str(chat_id).startswith('local:') and message_id:
            meta = {'chat_id': chat_id, 'message_id': message_id}
        file_item = upload_file_handler(
            request,
            file=uf,
            metadata=meta,
            process=False,
            user=user,
        )
        if not file_item or not getattr(file_item, 'id', None):
            _fail_message(form_data, tr, 'upload')
            return form_data

        if chat_id and not str(chat_id).startswith('local:') and message_id:
            try:
                Chats.insert_chat_files(
                    chat_id=chat_id,
                    message_id=message_id,
                    file_ids=[file_item.id],
                    user_id=user.id,
                )
            except Exception as e:
                log.debug('[MWS] insert_chat_files: %s', e)

        entry = _export_file_attachment_record(file_item, out_bytes, filename, content_type)
        form_data['_mws_export_result_files'] = [entry]
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
                    'data': {'files': [entry]},
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
    if kind == 'zip_pages':
        return (
            'ZIP hazır (her sayfa ayrı PDF). PNG rasterleme sunucuda yok; gerekirse masaüstünde dönüştürebilirsiniz.'
            if tr
            else 'ZIP is ready (one PDF per page). Raster PNG export is not available server-side.'
        )
    if kind == 'zip':
        return 'ZIP arşivi hazır.' if tr else 'ZIP archive is ready.'
    if kind == 'csv':
        return 'CSV dosyası hazır. Excel veya herhangi bir tablo uygulamasıyla açabilirsiniz.' if tr else 'CSV file is ready. You can open it with Excel or any spreadsheet application.'
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
    elif reason == 'no_source_image':
        msg = (
            'Dönüştürülecek görsel bulunamadı. Lütfen fotoğrafı mesaja ekleyip tekrar deneyin.'
            if tr
            else 'No source image found. Please attach the image and try again.'
        )
    elif reason == 'unsupported':
        msg = (
            'PDF’yi doğrudan PNG/JPEG’e çevirmek bu sunucuda yok; sayfa başına ayrı PDF ZIP olarak isteyebilir veya metin çıkarımı deneyebilirsiniz.'
            if tr
            else 'PDF to PNG/JPEG raster is not available here; try page-split ZIP or text extraction.'
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
        get_file_bytes_from_source,
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
        if kind == 'text_csv' or target == 'csv':
            csv_bytes = _markdown_table_to_csv_bytes(text)
            return csv_bytes, f'{title_slug}.csv', 'text/csv', 'csv'
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
        ct = (artifact.get('content_type') or '').lower()
        name = (artifact.get('name') or '').lower()
        u = (artifact.get('url') or '').strip()
        fid = artifact.get('file_id')
        src = u or (str(fid) if fid else '')
        if not src:
            raise ValueError('unsupported_file_artifact')
        raw = get_file_bytes_from_source(src)
        is_pdf = 'pdf' in ct or name.endswith('.pdf') or raw[:5] == b'%PDF-'

        if is_pdf:
            if kind in ('image_raster', 'svg_embed') or target in ('png', 'jpeg', 'jpg', 'webp', 'svg'):
                raise ValueError('pdf_to_image_unsupported')
            if kind == 'image_pdf' or target == 'pdf':
                return raw, f'{title_slug}.pdf', 'application/pdf', 'pdf'
            if kind == 'pdf_extract_text' or (target == 'txt' and kind not in ('image_raster',)):
                from open_webui.utils.export_formats import pdf_bytes_extract_text

                text = pdf_bytes_extract_text(raw)
                data = text.encode('utf-8')
                return data, f'{title_slug}.txt', 'text/plain', 'txt'

        raise ValueError('unsupported_file_artifact')

    raise ValueError('unknown_artifact')
