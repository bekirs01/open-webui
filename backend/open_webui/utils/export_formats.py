"""
Markdown / metin içeriğini indirilebilir PDF veya PNG üretimi; görseli PDF'e gömme.
"""

from __future__ import annotations

import io
import logging
import os
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


def fpdf_output_bytes(pdf: FPDF) -> bytes:
    """
    Normalize fpdf2 output to raw PDF bytes.
    Some versions return str or bytearray; PDF binary must not be UTF-8 encoded.
    """
    raw = pdf.output()
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)
    if isinstance(raw, str):
        return raw.encode('latin-1')
    return bytes(raw)


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
    return fpdf_output_bytes(pdf)


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
    """
    Tek sayfa PDF: sayfa boyutu görüntüyle birebir (pt ≈ px), kenar boşluğu yok.
    A4 üzerine küçültüp beyaz çerçeve eklemez; görüntü tam sayfayı doldurur.
    """
    max_edge = int(os.environ.get('MWS_EXPORT_IMAGE_PDF_MAX_EDGE', '12240'))
    im = PILImage.open(io.BytesIO(image_bytes))
    iw, ih = im.size
    if iw < 1 or ih < 1:
        raise ValueError('invalid_image_dimensions')
    scale = min(1.0, float(max_edge) / float(max(iw, ih)))
    if scale < 1.0:
        try:
            resample = PILImage.Resampling.LANCZOS
        except AttributeError:
            resample = PILImage.LANCZOS  # Pillow < 9
        im = im.resize(
            (max(1, int(iw * scale)), max(1, int(ih * scale))),
            resample,
        )
        iw, ih = im.size

    if im.mode == 'P':
        im = im.convert('RGBA')

    buf = io.BytesIO()
    if im.mode in ('RGBA', 'LA'):
        im.save(buf, format='PNG', optimize=True)
    else:
        im.convert('RGB').save(buf, format='PNG', optimize=True)
    buf.seek(0)

    pw, ph = float(iw), float(ih)
    pdf = FPDF(orientation='P', unit='pt', format=(pw, ph))
    pdf.set_margins(0, 0, 0)
    pdf.set_auto_page_break(False, margin=0)
    pdf.add_page()
    pdf.image(buf, x=0, y=0, w=pw, h=ph)

    out = fpdf_output_bytes(pdf)
    if not _validate_pdf_magic(out):
        raise ValueError('invalid_pdf_from_image')
    return out


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
    return fpdf_output_bytes(pdf)


# --- Batch export / PDF utilities (pypdf, zip) ---

MAX_EXPORT_PDF_PAGES = int(os.environ.get('MWS_EXPORT_MAX_PDF_PAGES', '200'))
MAX_EXPORT_BATCH_IMAGES = int(os.environ.get('MWS_EXPORT_MAX_BATCH_IMAGES', '50'))
MAX_EXPORT_TOTAL_BYTES = int(os.environ.get('MWS_EXPORT_MAX_TOTAL_BYTES', str(48 * 1024 * 1024)))


def _validate_pdf_magic(b: bytes) -> bool:
    return bool(b) and len(b) >= 5 and b[:5] == b'%PDF-'


def get_file_bytes_from_source(url_or_id: str) -> bytes:
    """Open WebUI file id, API path, or http(s) URL — any stored file, not only images."""
    return get_image_bytes_from_source(url_or_id)


def multi_image_bytes_to_pdf_bytes(images: list[bytes]) -> bytes:
    """Birden fazla raster görüntüyü sayfa sırası korunarak tek PDF'e yazar."""
    if not images:
        raise ValueError('empty_image_list')
    if len(images) > MAX_EXPORT_BATCH_IMAGES:
        raise ValueError('too_many_images')
    total = 0
    for im in images:
        total += len(im or b'')
        if total > MAX_EXPORT_TOTAL_BYTES:
            raise ValueError('total_size_limit')
    from pypdf import PdfWriter

    writer = PdfWriter()
    for raw in images:
        if not raw or len(raw) < 32:
            raise ValueError('empty_image_bytes')
        one = image_bytes_to_pdf_bytes(raw)
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(one))
        for page in reader.pages:
            writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    data = out.getvalue()
    if not data or len(data) < 200:
        raise ValueError('empty_pdf_output')
    return data


def merge_pdf_bytes_list(parts: list[bytes]) -> bytes:
    """Birden fazla PDF'i sırayla birleştirir."""
    if not parts:
        raise ValueError('empty_pdf_list')
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    total_pages = 0
    for pbytes in parts:
        if not pbytes or not _validate_pdf_magic(pbytes):
            raise ValueError('invalid_pdf')
        if len(pbytes) > MAX_EXPORT_TOTAL_BYTES:
            raise ValueError('pdf_too_large')
        reader = PdfReader(io.BytesIO(pbytes))
        for page in reader.pages:
            writer.add_page(page)
            total_pages += 1
            if total_pages > MAX_EXPORT_PDF_PAGES:
                raise ValueError('too_many_pages')
    out = io.BytesIO()
    writer.write(out)
    data = out.getvalue()
    if not data or len(data) < 200:
        raise ValueError('empty_pdf_output')
    return data


def pdf_bytes_extract_text(pdf_bytes: bytes, max_chars: int = 1_500_000) -> str:
    """PDF metin çıkarımı (basit; taranmış sayfalar boş olabilir)."""
    if not pdf_bytes or not _validate_pdf_magic(pdf_bytes):
        raise ValueError('invalid_pdf')
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    if len(reader.pages) > MAX_EXPORT_PDF_PAGES:
        raise ValueError('too_many_pages')
    chunks: list[str] = []
    n = 0
    for page in reader.pages:
        try:
            t = page.extract_text() or ''
        except Exception:
            t = ''
        chunks.append(t)
        n += len(t)
        if n > max_chars:
            break
    return '\n\n'.join(chunks).strip() or '(Metin çıkarılamadı; dosya taranmış PDF olabilir.)'


def pdf_bytes_split_to_zip_entries(pdf_bytes: bytes) -> list[tuple[str, bytes]]:
    """
    Her PDF sayfasını ayrı tek sayfalık PDF olarak döndürür (sıra korunur).
    Görsellere rasterleme yok; kullanıcı sayfa başına PDF alır.
    """
    if not pdf_bytes or not _validate_pdf_magic(pdf_bytes):
        raise ValueError('invalid_pdf')
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(pdf_bytes))
    n = len(reader.pages)
    if n > MAX_EXPORT_PDF_PAGES:
        raise ValueError('too_many_pages')
    out: list[tuple[str, bytes]] = []
    for i, page in enumerate(reader.pages, start=1):
        w = PdfWriter()
        w.add_page(page)
        buf = io.BytesIO()
        w.write(buf)
        name = f'page_{i:03d}.pdf'
        out.append((name, buf.getvalue()))
    return out


def build_zip_bytes(entries: list[tuple[str, bytes]]) -> bytes:
    """Dosya adı + içerik listesinden ZIP üretir."""
    import zipfile

    if not entries:
        raise ValueError('empty_zip_entries')
    total = sum(len(b) for _, b in entries)
    if total > MAX_EXPORT_TOTAL_BYTES:
        raise ValueError('total_size_limit')
    buf = io.BytesIO()
    seen: set[str] = set()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            safe = name.replace('..', '_').replace('/', '_')[:180] or 'file.bin'
            base = safe
            i = 0
            while safe in seen:
                i += 1
                stem = base.rsplit('.', 1)
                safe = f'{stem[0]}_{i}.{stem[1]}' if len(stem) == 2 else f'{base}_{i}'
            seen.add(safe)
            zf.writestr(safe, data)
    return buf.getvalue()


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
