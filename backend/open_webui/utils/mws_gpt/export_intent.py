"""
Detect user intent to export or convert the last assistant output to another format.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

ExportKind = Literal[
    'image_raster',
    'image_pdf',
    'text_pdf',
    'text_plain',
    'text_markdown',
    'text_json',
    'text_csv',
    'svg_embed',
    'archive_zip',
    'pdf_merge',
    'pdf_extract_text',
    'pdf_split_zip',
    'conversion_unavailable',
]


@dataclass(frozen=True)
class ExportIntent:
    """Parsed export request."""

    kind: ExportKind
    target: str  # pdf | png | zip | txt | …
    unavailable_code: str | None = None


# Short imperative lines (TR/EN)
_EXPORT_LINE = re.compile(
    r'^\s*(?:bunu\s+|şunu\s+|ayn[ıi]\s+|the\s+)?'
    r'(?:'
    r'(?:pdf|png|jpe?g|jpeg|webp|svg|csv)\s*(?:yap|ver|olarak\s+ver|format[ıi]na\s+çevir|formatına\s+cevir|formatına\s+çevir|çevir|cevir|dönüştür|donustur|indir)|'
    r'(?:pdf|png|jpe?g|jpeg|webp|csv)\s+format|'
    r'pdf\s+format[ıi]na|'
    r'(?:export|save|download|convert)\s*(?:as|to)?\s*(?:pdf|png|jpe?g|jpeg|webp|svg|csv)?|'
    r'(?:dosya|indirilebilir)\s+(?:olarak\s+)?(?:hazırla|hazırlay|ver)|'
    r'(?:markdown|metin|text)\s+olarak\s+ver|'
    r'(?:tabloyu|bu\s+tabloyu)\s+(?:indir|kaydet|csv|excel)'
    r')'
    r'[.!?\s]*$',
    re.I,
)

_INLINE_EXPORT = re.compile(
    r'(?:^|[\s,.;])'
    r'(?:'
    r'(?:pdf|png|jpe?g|jpeg|webp|svg|csv)\s*(?:yap|ver)|'
    r'pdf\s+format[ıi]na\s+çevir|pdf\s+formatina\s+cevir|'
    r'csv\s+(?:olarak|formatında|formatina)\s+(?:ver|çevir|cevir|indir)|'
    r'excel\s*(?:e|\'e)?\s+(?:çevir|cevir|aktar|ver)|'
    r'export\s+as\s+\w+|convert\s+to\s+\w+'
    r')'
    r'(?:\s|$|[.!?])',
    re.I,
)

# Turkish: pdf'e çevir, png'ye çevir, jpeg'e çevir (apostrophe variants)
_TR_SUFFIX_CEvir = re.compile(
    r'\b(?:pdf|png|jpe?g|jpeg|webp|svg|csv)[\u2019\'`]?(?:e|a|ye|ya)\s+(?:çevir|cevir|dönüştür|donustur)\b',
    re.I,
)

# "png ver", "jpg ver", "csv ver" at end of short message
_TR_FORMAT_VER = re.compile(
    r'^\s*(?:bunu\s+|şunu\s+)?(?:pdf|png|jpe?g|jpeg|webp|svg|csv)\s+ver\s*\.?\s*$',
    re.I,
)

_AMBIGUOUS_FORMAT = re.compile(
    r'\b(?:başka|baska|farklı|farkli|diğer|diger)\s+format',
    re.I,
)

_EXPORT_ET = re.compile(r'\bexport\s+et\b', re.I)


def _norm(s: str) -> str:
    return (s or '').strip()


def parse_structured_export_intent(message_text: str) -> ExportIntent | None:
    """
    Çoklu dosya / PDF işlemleri / ZIP — metin tabanlı niyet (ekler pipeline'da çözülür).
    """
    t = _norm(message_text)
    if not t or len(t) > 800:
        return None
    low = t.lower()

    # CSV / Excel / spreadsheet
    if re.search(
        r'\b(?:csv|excel|xlsx?|spreadsheet)\b',
        low,
    ) and re.search(r'\b(?:çevir|cevir|ver|yap|export|convert|olarak|indir|kaydet|aktar)\b', low):
        return ExportIntent('text_csv', 'csv')
    if re.search(r'\b(?:tabloyu|bu\s+tabloyu|tablo)\s+(?:indir|kaydet|csv|excel)', low):
        return ExportIntent('text_csv', 'csv')

    # DOCX / Word — sunucuda üretim yok
    if re.search(
        r'\b(?:docx|\.doc\b|word\s+belgesi|microsoft\s+word|word\s+olarak|word\s+format)\b',
        low,
    ) or (
        re.search(r'(?<![a-z])word(?![a-z])', low)
        and re.search(r'\b(?:çevir|cevir|ver|yap|export|convert|olarak)\b', low)
    ):
        if re.search(r'\b(?:çevir|cevir|ver|yap|export|convert|olarak|format)\b', low):
            return ExportIntent('conversion_unavailable', 'docx', unavailable_code='docx')

    # ZIP / arşiv
    if re.search(
        r'^\s*(?:bunlar[ıi]?|şunlar[ıi]?|hepsini|tümünü|tumunu|şunları|sunları)\s+(?:bir\s+)?zip\b',
        low,
    ) or re.search(r'\b(?:zip|arşiv|arsiv)\s+(?:yap|ver|oluştur|olustur|indir|olarak)\b', low):
        return ExportIntent('archive_zip', 'zip')
    if re.search(r'\b(?:sıkıştır|sikistır|pack\s+as\s+zip|make\s+a\s+zip)\b', low):
        return ExportIntent('archive_zip', 'zip')

    # Çoklu görsel → tek PDF (açık ifade)
    if re.search(
        r'(?:bunlar|şunlar|hepsi|tüm\s|tum\s|foto[ğg]raf|foto|resim).{0,64}(?:tek|bir)\s*pdf',
        low,
    ) or re.search(r'\b(?:tek|bir|single|one)\s+pdf\b', low) and re.search(
        r'\b(?:yap|ver|birleştir|birlestir|merge|combine|oluştur)\b',
        low,
    ):
        return ExportIntent('image_pdf', 'pdf')

    # PDF birleştir
    if re.search(r'\b(?:birleştir|birlestir|merge|combine)\b', low) and re.search(r'\bpdf\b', low):
        return ExportIntent('pdf_merge', 'pdf')

    # PDF → metin / txt
    if re.search(r'\bpdf\b', low) and re.search(
        r'\b(?:txt|metin|düz\s+metin|düz\s+metin|plain\s+text|text\s+file)\b',
        low,
    ) and re.search(r'\b(?:çevir|cevir|çıkar|cikar|extract|ver|olarak)\b', low):
        return ExportIntent('pdf_extract_text', 'txt')

    # PDF sayfa ayır → ZIP (sayfa başına PDF; PNG raster yok)
    if re.search(r'\bpdf\b', low) and re.search(
        r'(?:görsellere\s+ayır|gorsellere\s+ayır|sayfalara\s+(?:böl|bol)|her\s+sayfa|sayfa\s+sayfa|split\s+(?:into\s+)?pages|page[\s-]+by[\s-]+page)',
        low,
    ):
        return ExportIntent('pdf_split_zip', 'zip')

    return None


def parse_export_intent(message_text: str) -> ExportIntent | None:
    """
    If the user is clearly asking for a file format conversion/export, return intent.
    Conservative: avoids classifying general questions about PDF/PNG as export.
    """
    st = parse_structured_export_intent(message_text)
    if st:
        return st

    t = _norm(message_text)
    if not t or len(t) > 800:
        return None

    low = t.lower()

    # Long explanatory questions — not export
    if re.search(r'\b(what is|nedir|nasıl|why|neden|explain|açıkla|tanım)\b', low):
        if not _INLINE_EXPORT.search(t) and not _TR_SUFFIX_CEvir.search(t):
            return None

    # Turkish "pdf'e çevir" style (often missed by line-anchored regex)
    if _TR_SUFFIX_CEvir.search(t):
        return _intent_from_text(low, t)

    if _TR_FORMAT_VER.match(t):
        return _intent_from_text(low, t)

    if _AMBIGUOUS_FORMAT.search(t) and re.search(
        r'\b(?:çevir|cevir|ver|yap|dönüştür|donustur|indir)\b',
        low,
    ):
        return ExportIntent('image_pdf', 'pdf')

    if len(t) < 100 and _EXPORT_ET.search(t):
        return ExportIntent('image_pdf', 'pdf')

    if _EXPORT_LINE.match(t) or (len(t) < 120 and _INLINE_EXPORT.search(t)):
        return _intent_from_text(low, t)

    if re.search(
        r'\b(?:pdf|png|jpe?g|jpeg|webp)\s+format[ıi]na\s+(?:çevir|cevir|dönüştür|donustur)\b',
        low,
    ):
        return _intent_from_text(low, t)
    if re.search(r'\b(?:export|convert)\s+(?:to|as)\s+(?:pdf|png|jpe?g|jpeg|webp|svg)\b', low):
        return _intent_from_text(low, t)
    if re.search(r'\b(?:save|download)\s+as\s+(?:pdf|png|jpe?g|jpeg|webp)\b', low):
        return _intent_from_text(low, t)

    if re.search(r'\b(?:pdf|png|jpe?g|jpeg|webp)\s+olarak\s+ver\b', low):
        return _intent_from_text(low, t)

    # Kısa: dışa aktar / export
    if len(t) < 120 and re.search(r'^\s*(?:dışa\s*aktar|disa\s*aktar|export)\s*\.?\s*$', low):
        return ExportIntent('image_raster', 'png')

    return None


def _intent_from_text(low: str, raw: str) -> ExportIntent | None:
    if re.search(r'\b(csv|excel|xlsx?|spreadsheet|tablo.{0,20}indir|tabloyu.{0,20}kaydet)\b', low):
        return ExportIntent('text_csv', 'csv')

    if 'json' in low and any(
        k in low for k in ('json', 'export', 'indir', 'save', 'ver', 'olarak')
    ):
        if re.search(r'\bjson\b', low) and len(raw) < 200:
            return ExportIntent('text_json', 'json')

    if re.search(r'\b(md|markdown)\b', low) and any(
        k in low for k in ('olarak', 'as', 'export', 'markdown', 'md ')
    ):
        return ExportIntent('text_markdown', 'md')

    if re.search(r'\b(txt|text\s+file|düz\s+metin)\b', low):
        return ExportIntent('text_plain', 'txt')

    if 'svg' in low:
        return ExportIntent('svg_embed', 'svg')

    if re.search(r'\bjpe?g\b|\bjpeg\b', low):
        return ExportIntent('image_raster', 'jpeg')
    if 'png' in low:
        return ExportIntent('image_raster', 'png')
    if 'webp' in low:
        return ExportIntent('image_raster', 'webp')

    if 'pdf' in low:
        return ExportIntent('image_pdf', 'pdf')

    return None


def export_intent_blocks_web_search(message_text: str) -> bool:
    return resolve_export_intent(message_text) is not None


def wants_downloadable_delivery(message_text: str) -> ExportIntent | None:
    """
    Geniş niyet: kullanıcı açıkça indirilebilir dosya / dönüştürme istiyor ama
    parse_export_intent satır/format regex'ine takılmamış olabilir.
    """
    t = (message_text or '').strip()
    if not t or len(t) > 520:
        return None
    low = t.lower()
    # Öğretim / tanım soruları
    if re.search(
        r'\b(what is a pdf|pdf nedir|png nedir|nedir\s+pdf)\b',
        low,
    ):
        return None

    st = parse_structured_export_intent(t)
    if st:
        return st

    # Türkçe: indirilebilir formata / dosya olarak / bana indir
    # (ı/i karışımları ve "formatta ver" kısa istekleri)
    broad_tr = (
        'indirilebilir formata',
        'indirilebilir formatta',
        'ındırılabilir formatta',
        'ındırılabilir formata',
        'indirilebilir format',
        'indirilebilir formatta ver',
        'indirilebilir formata ver',
        'indirilebilir ver',
        'indirilebilir dosya',
        'indirebileyim',
        'indirebilmem',
        'indirebileceğim',
        'indirebilecegim',
        'dosya olarak ver',
        'dosya olarak indir',
        'dosya halinde',
        'indirilebilir hale',
        'çıktıyı dosya',
        'tabloyu indir',
        'tabloyu kaydet',
        'tabloyu csv',
        'tabloyu excel',
        'görseli pdf',
        'görseli png',
        'resmi pdf',
        'resmi png',
        'resmi indir',
        'görseli indir',
        'fotoğrafı indir',
        'fotografi indir',
        'bunu dosya',
        'şunu dosya',
        'kaydedilebilir',
        'oluşturduğun görseli',
        'olusturdugun gorseli',
        'dışa aktar',
        'disa aktar',
        'bunu indir',
        'şunu indir',
        'bunu kaydet',
        'istediğim formatta',
        'istedigim formatta',
        'istediğim format',
        'formata çevir',
        'formata cevir',
        'formatında ver',
        'formatinda ver',
    )
    if any(x in low for x in broad_tr):
        return _intent_from_text(low, t) or ExportIntent('image_raster', 'png')

    if re.search(r'^\s*(?:bunu|şunu)\s+indirilebilir\b', low) and len(t) < 160:
        return ExportIntent('image_raster', 'png')

    # Kısa emir: "bana indir", "download this"
    if len(t) < 140:
        if re.search(
            r'^\s*(?:bunu|şunu|ayn[ıi]şeyi|tabloyu|görseli|foto[ğg]raf[ıi]|çıktıyı|ciktiyi)\s+indir\b',
            low,
        ):
            return ExportIntent('image_pdf', 'pdf')
        if re.search(r'^\s*(download|save)\s+(this|it|that)\b', low):
            return _intent_from_text(low, t) or ExportIntent('image_pdf', 'pdf')

    if re.search(
        r'\b(downloadable\s+format|as\s+a\s+file|save\s+as\s+(?:pdf|png))\b',
        low,
    ):
        return _intent_from_text(low, t) or ExportIntent('image_pdf', 'pdf')

    return None


def resolve_export_intent(message_text: str) -> ExportIntent | None:
    """Önce yapılandırılmış / kesin eşleşme; sonra geniş 'indirilebilir dosya' niyeti."""
    return parse_export_intent(message_text) or wants_downloadable_delivery(message_text)


def adjust_intent_for_attachment_counts(
    intent: ExportIntent,
    *,
    n_images: int,
    n_pdfs: int,
    message_lower: str,
) -> ExportIntent:
    """
    Çoklu yüklemede 'indirilebilir ver' gibi belirsiz istekleri ZIP'e çevir;
    açık 'png/jpeg' isteğinde çoklu görselde ZIP'e düş (tek PNG anlamsız).
    """
    low = (message_lower or '').lower()
    if intent.kind == 'conversion_unavailable':
        return intent

    # Açıkça zip / pdf / format istendiyse dokunma
    if re.search(r'\b(?:zip|arşiv|arsiv|pdf|png|jpe?g|jpeg|webp|svg|txt|markdown|json)\b', low):
        if 'zip' in low or 'arşiv' in low or 'arsiv' in low:
            return intent
        if intent.kind in ('archive_zip', 'pdf_merge', 'pdf_split_zip', 'pdf_extract_text'):
            return intent
        if n_images >= 2 and intent.kind == 'image_pdf':
            return intent

    if n_images >= 2 and intent.kind == 'image_raster' and intent.target in ('png', 'jpeg', 'webp'):
        if not re.search(r'\b(?:tek|bir|single|one|merge|birleş)\b', low):
            return ExportIntent('archive_zip', 'zip')

    if n_images >= 2 and intent.kind == 'image_raster' and intent.target == 'png':
        if re.search(r'\bindirilebilir|downloadable|dosya\s+olarak|as\s+a\s+file\b', low):
            return ExportIntent('archive_zip', 'zip')

    return intent
