"""
Resolve the most recent user-visible artifact (image, assistant text) for export follow-ups.
"""

from __future__ import annotations

import re
from typing import Any

_MARKDOWN_IMG = re.compile(r'!\[[^\]]*\]\(([^)]+)\)')


def extract_last_image_artifact_for_export(messages: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """
    Last assistant raster image only (for image→PDF/PNG/JPEG/WEBP).

    Skips non-image attachments (e.g. a prior PDF export) so repeated format
    requests still convert from the original generated image.
    """
    if not messages:
        return None

    tail_user = _last_user_index(messages)
    search = messages[:tail_user] if tail_user is not None else messages

    for m in reversed(search):
        if m.get('role') != 'assistant':
            continue

        for f in m.get('files') or []:
            if not isinstance(f, dict):
                continue
            url = (f.get('url') or '').strip()
            ct = (f.get('content_type') or '').lower()
            typ = f.get('type')
            fid = f.get('id')
            if typ == 'image' or ct.startswith('image/'):
                if url:
                    return {'kind': 'image', 'url': url, 'file_id': fid}
                if fid:
                    return {'kind': 'image', 'url': str(fid), 'file_id': fid}

        img_url = _image_url_from_content(m.get('content'))
        if img_url:
            return {'kind': 'image', 'url': img_url, 'file_id': None}

    return None


def extract_last_artifact_for_export(messages: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """
    Inspect conversation messages (before LLM-specific stripping). Returns last exportable artifact
    from assistant messages before the final user turn.
    """
    if not messages:
        return None

    tail_user = _last_user_index(messages)
    search = messages[:tail_user] if tail_user is not None else messages

    for m in reversed(search):
        if m.get('role') != 'assistant':
            continue

        for f in m.get('files') or []:
            if not isinstance(f, dict):
                continue
            ct = (f.get('content_type') or f.get('type') or '').lower()
            url = f.get('url') or ''
            if f.get('type') == 'image' or ct.startswith('image/'):
                if url:
                    return {
                        'kind': 'image',
                        'url': url,
                        'file_id': f.get('id'),
                    }
            if f.get('type') == 'file' and url and not ct.startswith('image/'):
                # prior document export
                return {
                    'kind': 'file',
                    'url': url,
                    'file_id': f.get('id'),
                    'content_type': ct,
                }

        img_url = _image_url_from_content(m.get('content'))
        if img_url:
            return {'kind': 'image', 'url': img_url, 'file_id': None}

        text = _assistant_text(m)
        if text and len(text.strip()) > 2:
            return {
                'kind': 'text',
                'text': text.strip(),
            }

    return None


def _last_user_index(messages: list[dict[str, Any]]) -> int | None:
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get('role') == 'user':
            return i
    return None


def _assistant_text(m: dict[str, Any]) -> str:
    c = m.get('content')
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts: list[str] = []
        for p in c:
            if not isinstance(p, dict):
                continue
            if p.get('type') == 'text':
                parts.append(p.get('text') or '')
        return '\n'.join(parts)
    return ''


def _image_url_from_content(content: Any) -> str | None:
    if isinstance(content, str):
        m = _MARKDOWN_IMG.search(content)
        if m:
            return m.group(1).strip()
        # Relative API path without markdown (some UIs embed plain path)
        m2 = re.search(r'(/api/v\d+/files/[0-9a-f-]{36}/content[^\s\)]*)', content, re.I)
        if m2:
            return m2.group(1).strip()
        # bare URL line
        if content.strip().startswith('http') and '://' in content[:12]:
            return content.strip().split()[0]
    if isinstance(content, list):
        for p in content:
            if not isinstance(p, dict):
                continue
            if p.get('type') in ('image_url', 'image'):
                iu = p.get('image_url')
                if isinstance(iu, dict):
                    u = iu.get('url')
                    if u:
                        return str(u).strip()
    return None


def guess_user_language_turkish(message_text: str) -> bool:
    t = message_text or ''
    if re.search(r'[ğüşöçıİĞÜŞÖÇ]', t):
        return True
    low = t.lower()
    tr_kw = (
        'bunu',
        'şunu',
        'pdf',
        'yap',
        'çevir',
        'format',
        'indir',
        'olarak',
        'dosya',
        'hazır',
    )
    return any(k in low for k in tr_kw)
