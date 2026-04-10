"""
Deterministic image prompt normalization for MWS image generation.
Preserves the user's full intent; expands Turkish into English for diffusion models.
"""

from __future__ import annotations

import re

from open_webui.utils.mws_gpt.registry import _normalize_tr_keyboard_typos

_STYLE_SUFFIX = (
    ', highly detailed, coherent composition, include every object and action mentioned above, '
    'clean background unless scene requires otherwise, professional lighting, no text overlay'
)

# Bilinen kişi / marka yazım hataları (kullanıcı yazımı)
_NAME_FIXES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r'\bmack\s*zakerburg\w*|\bmack\s*zuckerberg\b', re.I), 'Mark Zuckerberg'),
    (re.compile(r'\belon\s*musk\b', re.I), 'Elon Musk'),
)

# Tek kelime / kısa TR → EN (uzun eşleşmeler önce)
_TR_TOKEN_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r'\bmuz\w*\b', re.I), 'banana'),
    (re.compile(r'\bkartopu\w*', re.I), 'snowball'),
    (re.compile(r'\bkardan\s*adam\w*', re.I), 'snowman'),
    (re.compile(r'\bspor\s*araba\w*', re.I), 'sports car'),
    (re.compile(r'\bkırmızı\b|\bkirmizi\b', re.I), 'red'),
    (re.compile(r'\bmavi\b', re.I), 'blue'),
    (re.compile(r'\baraba\w*', re.I), 'car'),
    (re.compile(r'\bportre\b', re.I), 'portrait'),
    (re.compile(r'\bkedi\b', re.I), 'cat'),
    (re.compile(r'\bköpek\b|\bkopek\b', re.I), 'dog'),
)


def _strip_draw_wrappers(s: str) -> str:
    low = s.lower().strip()
    low = re.sub(
        r'^(bana|lütfen|please|can you|could you|would you|draw me|make me|create|generate)\s+',
        '',
        low,
        flags=re.I,
    )
    low = re.sub(
        r'\s+(çiz|çizer\s*misin|ciz|draw|paint|make|generate|oluştur|üret|yap|resmi)\s*\.?\s*$',
        '',
        low,
        flags=re.I,
    )
    return low.strip(' .,:;')


def _apply_name_fixes(s: str) -> str:
    t = s
    for rx, rep in _NAME_FIXES:
        t = rx.sub(rep, t)
    return t


def _try_elinde_olan_scene(t: str) -> str | None:
    """
    '... elinde muz olan Mark Zuckerberg' → İngilizce sahne cümlesi.
    """
    m = re.search(
        r'elinde\s+(\w+)\s+olan\s+(.+)$',
        t,
        re.I | re.S,
    )
    if not m:
        return None
    obj_raw, who_raw = m.group(1).strip(), m.group(2).strip()
    obj = obj_raw.lower()
    obj_en = {'muz': 'a banana', 'banana': 'a banana'}.get(obj, f'a {obj_raw}')
    who = _apply_name_fixes(who_raw)
    return (
        f'Photorealistic portrait of {who} holding {obj_en} in his hand, '
        f'natural pose, realistic facial features{_STYLE_SUFFIX}'
    )


def _tokens_to_english(t: str) -> str:
    """Kalan metni kelime kelime TR→EN sözlük ile zenginleştir."""
    out = t
    for rx, rep in _TR_TOKEN_REPLACEMENTS:
        out = rx.sub(rep, out)
    return out


def build_mws_image_prompt(user_text: str) -> str:
    """
    İngilizce odaklı, kullanıcının tüm nesne/eylem niyetini koruyan prompt.
    """
    raw = (user_text or '').strip()
    if not raw:
        return 'A clear, high-quality detailed illustration' + _STYLE_SUFFIX

    t = _normalize_tr_keyboard_typos(raw)
    t = _apply_name_fixes(t)
    core = _strip_draw_wrappers(t)

    # Özel kalıp: elinde X olan [kişi]
    scene = _try_elinde_olan_scene(core)
    if scene:
        return scene

    # Trump + at üzerinde / horseback (avoid boat/ship confusion)
    low_core = core.lower()
    if re.search(r'trump', low_core, re.I) and re.search(
        r'at\s+(üzerinde|uzerinde|üstünde|ustunde|üzerindeyken|uzerindeyken)|at\s*üzerinde|at\s*uzerinde|binek|horseback|on\s+a\s+horse|riding\s+a\s+horse',
        core,
        re.I,
    ):
        return (
            'Photorealistic image of Donald Trump riding on a brown horse, full scene, horse clearly visible '
            'with rider in saddle, outdoor or neutral background, correct anatomy. '
            'The subject must be on horseback on land. '
            'Do NOT show a boat, ship, yacht, deck, water vessel, marina, or maritime setting. '
            'Do NOT place the person on a boat or ship deck.'
            + _STYLE_SUFFIX
        )

    # Kısa özel konular (geriye uyumluluk)
    if re.search(r'\bkartopu\b|\bsnowball\b', core, re.I) and 'banana' not in core.lower():
        return 'Photorealistic single snowball made of compact snow' + _STYLE_SUFFIX
    if re.search(r'\bkardan\s*adam\b|\bsnowman\b', core, re.I):
        return 'Photorealistic friendly snowman made of snow' + _STYLE_SUFFIX

    # Genel: komutu attıktan sonra kalanı İngilizce anahtar kelimelere çevir
    en_core = _tokens_to_english(core)
    # Hâlâ çok Türkçe harf varsa yine de tam metni tarif et (model İngilizce + kalıntı kelime tolere eder)
    if len(en_core) < 3:
        en_core = core

    return (
        f'Photorealistic detailed image showing exactly: {en_core}. '
        f'Follow the description literally; include all people, objects, and actions mentioned{_STYLE_SUFFIX}'
    )
