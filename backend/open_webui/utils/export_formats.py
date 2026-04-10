"""
Markdown / metin içeriğini indirilebilir PDF veya PNG üretimi; görseli PDF'e gömme.
"""

from __future__ import annotations

import io
import logging
import re
import site
from html import escape
from pathlib import Path
import markdown
import requests
from fpdf import FPDF
from PIL import Image as PILImage

from open_webui.env import FONTS_DIR

log = logging.getLogger(__name__)


def _fpdf_with_unicode_fonts() -> FPDF:
    pdf = FPDF()
    pdf.add_page()
    fonts_dir = FONTS_DIR
    if not fonts_dir.exists():
        fonts_dir = Path(site.getsitepackages()[0]) / 'static/fonts'
    if not fonts_dir.exists():
        fonts_dir = Path('.') / 'backend' / 'static' / 'fonts'

    try:
        pdf.add_font('NotoSans', '', str(fonts_dir / 'NotoSans-Regular.ttf'))
        pdf.add_font('NotoSans', 'b', str(fonts_dir / 'NotoSans-Bold.ttf'))
        pdf.add_font('NotoSans', 'i', str(fonts_dir / 'NotoSans-Italic.ttf'))
        pdf.add_font('NotoSansKR', '', str(fonts_dir / 'NotoSansKR-Regular.ttf'))
        pdf.add_font('NotoSansJP', '', str(fonts_dir / 'NotoSansJP-Regular.ttf'))
        pdf.add_font('NotoSansSC', '', str(fonts_dir / 'NotoSansSC-Regular.ttf'))
        pdf.add_font('Twemoji', '', str(fonts_dir / 'Twemoji.ttf'))
        pdf.set_font('NotoSans', size=11)
        pdf.set_fallback_fonts(['NotoSansKR', 'NotoSansJP', 'NotoSansSC', 'Twemoji'])
    except Exception as e:
        log.warning('export_formats: Noto fonts missing, using core font: %s', e)
        pdf.set_font('Helvetica', size=11)

    pdf.set_auto_page_break(auto=True, margin=15)
    return pdf


def markdown_to_pdf_bytes(title: str, markdown_text: str) -> bytes:
    """Markdown (tablo dahil) içeriğinden PDF baytları üretir."""
    title = (title or 'Export').strip() or 'Export'
    md = markdown_text or ''
    try:
        body = markdown.markdown(
            md,
            extensions=['tables', 'fenced_code', 'nl2br'],
        )
    except Exception as e:
        log.warning('markdown_to_pdf_bytes: markdown parse failed, using escaped text: %s', e)
        body = f'<pre>{escape(md)}</pre>'

    safe_title = escape(title)
    html = f"""
    <html><head><meta charset="utf-8"/></head>
    <body>
    <h1>{safe_title}</h1>
    <div class="content">{body}</div>
    </body></html>
    """
    pdf = _fpdf_with_unicode_fonts()
    try:
        pdf.write_html(html)
    except Exception as e:
        log.warning('markdown_to_pdf_bytes: write_html failed, fallback to plain text: %s', e)
        pdf = _fpdf_with_unicode_fonts()
        pdf.multi_cell(0, 6, md.replace('\r\n', '\n') or '(empty)')
    raw = pdf.output()
    return raw if isinstance(raw, (bytes, bytearray)) else bytes(raw)


def text_to_png_bytes(title: str, body: str, max_width: int = 1100) -> bytes:
    """Düz metin / tablo çizgilerini PNG olarak rasterize eder (görselleştirme / önizleme)."""
    from PIL import ImageDraw, ImageFont

    title = (title or '').strip()
    text = (body or '').strip() or ' '
    lines: list[str] = []
    if title:
        lines.append(title)
        lines.append('')
    for block in text.split('\n'):
        if len(block) <= max_width // 7:
            lines.append(block)
            continue
        # Uzun satırları böl (yaklaşık monospace genişliği)
        w = max(40, max_width // 8)
        for i in range(0, len(block), w):
            lines.append(block[i : i + w])

    font_path = FONTS_DIR / 'NotoSans-Regular.ttf'
    try:
        if font_path.is_file():
            font = ImageFont.truetype(str(font_path), 16)
            font_title = ImageFont.truetype(str(font_path), 20)
        else:
            raise OSError('no noto')
    except Exception:
        font = ImageFont.load_default()
        font_title = font

    line_h = 22
    pad = 24
    img_w = min(max_width, 1400)
    n = len(lines)
    img_h = pad * 2 + (n + 1) * line_h

    img = PILImage.new('RGB', (img_w, img_h), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    y = pad
    for i, line in enumerate(lines):
        f = font_title if i == 0 and title and lines[0] == title else font
        draw.text((pad, y), line, fill=(20, 20, 20), font=f)
        y += line_h

    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


def image_bytes_to_pdf_bytes(image_bytes: bytes) -> bytes:
    """Tek bir raster görüntüyü tek sayfalık PDF'e yerleştirir."""
    pdf = _fpdf_with_unicode_fonts()
    im = PILImage.open(io.BytesIO(image_bytes))
    if im.mode in ('RGBA', 'LA') or (im.mode == 'P' and 'transparency' in im.info):
        bg = PILImage.new('RGB', im.size, (255, 255, 255))
        src = im.convert('RGBA')
        bg.paste(src, mask=src.split()[3])
        im = bg
    else:
        im = im.convert('RGB')
    iw, ih = im.size
    page_w = pdf.w - 20
    scale = page_w / float(iw)
    disp_h = ih * scale
    if disp_h > pdf.h - 20:
        scale = (pdf.h - 20) / float(ih)
        disp_w = iw * scale
        disp_h = ih * scale
    else:
        disp_w = page_w
    buf = io.BytesIO()
    im.save(buf, format='PNG')
    buf.seek(0)
    pdf.image(buf, x=10, y=10, w=disp_w, h=disp_h)
    raw = pdf.output()
    return raw if isinstance(raw, (bytes, bytearray)) else bytes(raw)


def _extract_openwebui_file_id(url_or_path: str) -> str | None:
    """
    UI often stores image URLs as relative paths:
    /api/v1/files/<uuid>/content — resolve to raw file id for DB + disk read.
    """
    s = (url_or_path or '').strip()
    if not s:
        return None
    m = re.search(
        r'/files/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',
        s,
        re.I,
    )
    if m:
        return m.group(1)
    # Bare UUID (legacy / direct id)
    if re.fullmatch(
        r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
        s,
        re.I,
    ):
        return s.lower()
    return None


def get_image_bytes_from_source(url_or_id: str) -> bytes:
    """HTTP(S), data:image veya Open WebUI dosya kimliğinden görüntü baytları."""
    u = (url_or_id or '').strip()
    if not u:
        raise ValueError('Empty image URL or file id')
    if u.startswith('data:image'):
        b, _ = fetch_image_bytes(u)
        return b

    file_id = _extract_openwebui_file_id(u)
    if file_id:
        from pathlib import Path

        from open_webui.models.files import Files
        from open_webui.storage.provider import Storage

        f = Files.get_file_by_id(file_id)
        if not f:
            raise ValueError(f'File not found: {file_id}')
        p = Path(Storage.get_file(f.path))
        if not p.is_file():
            raise ValueError(f'File path missing: {file_id}')
        return p.read_bytes()

    if u.startswith(('http://', 'https://')):
        b, _ = fetch_image_bytes(u)
        return b
    from pathlib import Path

    from open_webui.models.files import Files
    from open_webui.storage.provider import Storage

    f = Files.get_file_by_id(u)
    if not f:
        raise ValueError(f'File not found: {u}')
    p = Path(Storage.get_file(f.path))
    if not p.is_file():
        raise ValueError(f'File path missing: {u}')
    return p.read_bytes()


def raster_image_bytes_to_format(image_bytes: bytes, fmt: str) -> tuple[bytes, str]:
    """
    Convert decoded image bytes to PNG, JPEG, or WEBP.
    Returns (bytes, content_type).
    """
    fmt_u = (fmt or 'PNG').upper()
    im = PILImage.open(io.BytesIO(image_bytes))
    if im.mode in ('RGBA', 'LA', 'P') and fmt_u in ('JPEG', 'JPG'):
        bg = PILImage.new('RGB', im.size, (255, 255, 255))
        src = im.convert('RGBA')
        bg.paste(src, mask=src.split()[3] if src.mode == 'RGBA' else None)
        im = bg
    elif im.mode != 'RGB' and fmt_u in ('JPEG', 'JPG'):
        im = im.convert('RGB')
    buf = io.BytesIO()
    if fmt_u in ('JPG', 'JPEG'):
        im.save(buf, format='JPEG', quality=92, optimize=True)
        return buf.getvalue(), 'image/jpeg'
    if fmt_u == 'WEBP':
        im.save(buf, format='WEBP', quality=90, method=6)
        return buf.getvalue(), 'image/webp'
    im.save(buf, format='PNG', optimize=True)
    return buf.getvalue(), 'image/png'


def image_bytes_to_svg_embed(image_bytes: bytes, title: str = 'export') -> str:
    """Valid SVG wrapping a base64 PNG (vector trace not available server-side)."""
    import base64

    im = PILImage.open(io.BytesIO(image_bytes))
    if im.mode in ('RGBA', 'LA') or (im.mode == 'P' and 'transparency' in im.info):
        bg = PILImage.new('RGB', im.size, (255, 255, 255))
        src = im.convert('RGBA')
        bg.paste(src, mask=src.split()[3])
        im = bg
    else:
        im = im.convert('RGB')
    buf = io.BytesIO()
    im.save(buf, format='PNG', optimize=True)
    b64 = base64.standard_b64encode(buf.getvalue()).decode('ascii')
    w, h = im.size
    esc = escape(title or 'export')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}">'
        f'<title>{esc}</title>'
        f'<image href="data:image/png;base64,{b64}" width="{w}" height="{h}"/>'
        f'</svg>'
    )


def plain_text_to_pdf_bytes(title: str, body: str) -> bytes:
    """Plain UTF-8 text to a simple PDF (no markdown)."""
    pdf = _fpdf_with_unicode_fonts()
    pdf.multi_cell(0, 6, (title or 'Export').strip() + '\n\n' + (body or '').replace('\r\n', '\n'))
    raw = pdf.output()
    return raw if isinstance(raw, (bytes, bytearray)) else bytes(raw)


def fetch_image_bytes(url: str, timeout: int = 30) -> tuple[bytes, str]:
    """HTTP(S) veya data URL'den görüntü baytları."""
    from open_webui.retrieval.web.utils import validate_url

    if url.startswith('data:image'):
        import base64
        import re

        m = re.match(r'data:image/(\w+);base64,(.+)', url, re.DOTALL | re.IGNORECASE)
        if not m:
            raise ValueError('Invalid data:image URL')
        return base64.b64decode(m.group(2)), f'image/{m.group(1)}'

    validate_url(url)
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    ct = r.headers.get('Content-Type', 'image/png').split(';')[0].strip()
    return r.content, ct
