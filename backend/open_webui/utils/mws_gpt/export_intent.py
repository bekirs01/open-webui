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
    'svg_embed',
]


@dataclass(frozen=True)
class ExportIntent:
    """Parsed export request."""

    kind: ExportKind
    target: str  # pdf | png | jpg | jpeg | webp | svg | txt | md | json


# Short imperative lines (TR/EN)
_EXPORT_LINE = re.compile(
    r'^\s*(?:bunu\s+|şunu\s+|ayn[ıi]\s+|the\s+)?'
    r'(?:'
    r'(?:pdf|png|jpe?g|jpeg|webp|svg)\s*(?:yap|ver|olarak\s+ver|format[ıi]na\s+çevir|formatına\s+cevir|formatına\s+çevir|çevir|cevir|dönüştür|donustur|indir)|'
    r'(?:pdf|png|jpe?g|jpeg|webp)\s+format|'
    r'pdf\s+format[ıi]na|'
    r'(?:export|save|download|convert)\s*(?:as|to)?\s*(?:pdf|png|jpe?g|jpeg|webp|svg)?|'
    r'(?:dosya|indirilebilir)\s+(?:olarak\s+)?(?:hazırla|hazırlay|ver)|'
    r'(?:markdown|metin|text)\s+olarak\s+ver'
    r')'
    r'[.!?\s]*$',
    re.I,
)

_INLINE_EXPORT = re.compile(
    r'(?:^|[\s,.;])'
    r'(?:'
    r'(?:pdf|png|jpe?g|jpeg|webp|svg)\s*(?:yap|ver)|'
    r'pdf\s+format[ıi]na\s+çevir|pdf\s+formatina\s+cevir|'
    r'export\s+as\s+\w+|convert\s+to\s+\w+'
    r')'
    r'(?:\s|$|[.!?])',
    re.I,
)

# Turkish: pdf'e çevir, png'ye çevir, jpeg'e çevir (apostrophe variants)
_TR_SUFFIX_CEvir = re.compile(
    r'\b(?:pdf|png|jpe?g|jpeg|webp|svg)[\u2019\'`]?(?:e|a|ye|ya)\s+(?:çevir|cevir|dönüştür|donustur)\b',
    re.I,
)

# "png ver", "jpg ver" at end of short message
_TR_FORMAT_VER = re.compile(
    r'^\s*(?:bunu\s+|şunu\s+)?(?:pdf|png|jpe?g|jpeg|webp|svg)\s+ver\s*\.?\s*$',
    re.I,
)

_AMBIGUOUS_FORMAT = re.compile(
    r'\b(?:başka|baska|farklı|farkli|diğer|diger)\s+format',
    re.I,
)

_EXPORT_ET = re.compile(r'\bexport\s+et\b', re.I)


def _norm(s: str) -> str:
    return (s or '').strip()


def parse_export_intent(message_text: str) -> ExportIntent | None:
    """
    If the user is clearly asking for a file format conversion/export, return intent.
    Conservative: avoids classifying general questions about PDF/PNG as export.
    """
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

    return None


def _intent_from_text(low: str, raw: str) -> ExportIntent | None:
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

    # Türkçe: indirilebilir formata / dosya olarak / bana indir
    broad_tr = (
        'indirilebilir formata',
        'indirilebilir formatta',
        'indirilebilir format',
        'indirilebilir ver',
        'indirilebilir dosya',
        'indirebileyim',
        'indirebilmem',
        'dosya olarak ver',
        'dosya olarak indir',
        'dosya halinde',
        'indirilebilir hale',
        'çıktıyı dosya',
        'tabloyu indir',
        'tabloyu kaydet',
        'görseli pdf',
        'görseli png',
        'bunu dosya',
        'şunu dosya',
        'kaydedilebilir',
    )
    if any(x in low for x in broad_tr):
        return _intent_from_text(low, t) or ExportIntent('image_raster', 'png')

    if re.search(r'^\s*(?:bunu|şunu)\s+indirilebilir\b', low) and len(t) < 160:
        return ExportIntent('image_raster', 'png')

    # Kısa emir: "bana indir", "download this"
    if len(t) < 140:
        if re.search(r'^\s*(?:bunu|şunu|ayn[ıi]şeyi|tabloyu|görseli|foto[ğg]raf[ıi])\s+indir\b', low):
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
    """Önce kesin eşleşme; olmazsa geniş 'indirilebilir dosya' niyeti."""
    return parse_export_intent(message_text) or wants_downloadable_delivery(message_text)
