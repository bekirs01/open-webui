"""
Reply-language / script detection, system-prompt reinforcement, and optional output cleanup.

Works across writing systems: Latin (all European languages), Cyrillic, CJK, Arabic, Hebrew,
Hangul, Thai, Indic, Greek, etc. No extra pip dependencies — Unicode ranges only.
"""

from __future__ import annotations

import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Literal

# Idempotency: merged into first system message in process_chat_payload
OUTPUT_LANGUAGE_LOCK_MARKER = '[OUTPUT_LANGUAGE_LOCK_v1]'
TURKISH_ORTHOGRAPHY_MARKER = '[USER_TURKISH_ORTHOGRAPHY_v1]'

_CYRILLIC = re.compile(r'[\u0400-\u04FF\u0500-\u052F]')
_GREEK = re.compile(r'[\u0370-\u03FF]')  # Greek (modern text; also covers Coptic start — rare)
# CJK / scripts that commonly leak from web snippets into wrong-language answers
_CJK = re.compile(r'[\u4E00-\u9FFF\u3400-\u4DBF\u3000-\u303F]')
_HIRAGANA = re.compile(r'[\u3040-\u309F]')
_KATAKANA = re.compile(r'[\u30A0-\u30FF]')
_HANGUL = re.compile(r'[\uAC00-\uD7AF\u1100-\u11FF]')
_ARABIC = re.compile(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]')
_HEBREW = re.compile(r'[\u0590-\u05FF]')
_THAI = re.compile(r'[\u0E00-\u0E7F]')
_LAO = re.compile(r'[\u0E80-\u0EFF]')
_DEVANAGARI = re.compile(r'[\u0900-\u097F]')
_BENGALI = re.compile(r'[\u0980-\u09FF]')
_MYANMAR = re.compile(r'[\u1000-\u109F]')
_GEORGIAN = re.compile(r'[\u10A0-\u10FF]')
_ETHIOPIC = re.compile(r'[\u1200-\u137F]')
_KHMER = re.compile(r'[\u1780-\u17FF]')
# Latin letters including extended (French, German, Vietnamese precomposed, etc.)
_LATIN_LETTER = re.compile(
    r'[a-zA-Z\u00C0-\u024F\u1E00-\u1EFF\u2C60-\u2C7F\uA720-\uA7FF]',
    re.UNICODE,
)

_TR_SPECIAL = frozenset('ğüşıöçĞÜŞÖÇİı')

_TR_HINTS = re.compile(
    r'(ve|i[cç]in|gibi|neden|nas[ıi]l|nerede|ka[cç]|mi|m[ıi]|mu|m[uü]|bir|bunu|'
    r'su|de|[sş]u|olarak|yok|var|daha|veya|ama|fakat|de[gğ]il|mi[sş]|t[uü]rk|l[üu]tfen|'
    r'nerel[iı]d[ıi]r|dogmus|do[ğg]mus|ka[çc]|misin|musun|değilim|yap[ıi]yor|'
    r'olmuş|içinde|hakk[ıi]nda)\b',
    re.IGNORECASE,
)

_EN_COMMON = re.compile(
    r'\b(?:the|and|that|this|what|when|where|which|who|why|how|your|from|with|have|'
    r'been|there|their|would|could|should|please|about|into|through|during|before|'
    r'after|than|then|them|they|these|those|very|just|also|only|even|much|many|some|'
    r'more|most|other|such|here|english|dollar|dollars|ruble|rubles|trump|'
    r"don't|doesn't|didn't|won't|can't|isn't|aren't|wasn't|haven't|hasn't|"
    r'does|did|has|had|was|were|are|is|am|not|can|will|shall|may|might|'
    # Short English-only prompts often lack “the/this/…” — still clearly English
    r'explain(?:s|ed|ing)?|shortly|briefly|thanks|thank\s+you)\b',
    re.IGNORECASE,
)

_RU_LATIN_HINTS = re.compile(
    r'\b(?:privet|poka|spasibo|zdravstvuy|zdravstvuite|kak|chto|gde|kogda|pochemu|'
    r'skolko|pozhaluista|ne|da|net|horosho|molodec|spasiba)\b',
    re.IGNORECASE,
)

# Broader “Indic / SEA letters” for user-script detection (not used to strip inside same family)
_INDISC_RANGE = re.compile(r'[\u0900-\u0DFF]')
_TIBETAN_RANGE = re.compile(r'[\u0F00-\u0FFF]')

# Degenerate model output: random CamelCase chains, path-like noise, code-token soup in plain prose
_LONG_URLISH = re.compile(r'https?://\S{20,}', re.I)


def _paragraph_is_degenerate_token_soup(p: str) -> bool:
    """Heuristic: block looks like mid-generation garbage, not human prose or markdown."""
    s = p.strip()
    ln = len(s)
    if ln < 120:
        return False

    humps = len(re.findall(r'[a-z][A-Z]', s))
    noise = sum(1 for c in s if c in '_/*\\[]{}()<>|`')
    space_ratio = s.count(' ') / max(ln, 1)

    if noise >= 18 and noise / ln > 0.035:
        return True
    if humps >= 16:
        return True
    if humps >= 10 and space_ratio < 0.065:
        return True

    body = _LONG_URLISH.sub('', s)
    if re.search(r'[A-Za-z0-9_./\\-]{95,}', body):
        return True

    return False


def _strip_token_soup_paragraphs(text: str) -> str:
    """Remove paragraph-sized blocks that match degenerate token-soup heuristics."""
    if not text or len(text) < 80:
        return text
    parts = re.split(r'\n\s*\n', text)
    kept = [p for p in parts if not _paragraph_is_degenerate_token_soup(p)]
    if not kept:
        return text.strip()
    out = '\n\n'.join(kept)
    return out if out.strip() else text


def _letter_chars(s: str) -> list[str]:
    return [c for c in s if c.isalpha()]


def _script_bucket(ch: str) -> str | None:
    """One primary script bucket per alphabetic character (first match wins)."""
    if not ch.isalpha():
        return None
    if _CYRILLIC.match(ch):
        return 'cyrillic'
    if _GREEK.match(ch):
        return 'greek'
    if _HANGUL.match(ch):
        return 'hangul'
    if _HIRAGANA.match(ch) or _KATAKANA.match(ch):
        return 'kana'
    if _CJK.match(ch):
        return 'han'
    if _ARABIC.match(ch):
        return 'arabic'
    if _HEBREW.match(ch):
        return 'hebrew'
    if _THAI.match(ch):
        return 'thai'
    if _LAO.match(ch):
        return 'lao'
    if _INDISC_RANGE.match(ch) or _TIBETAN_RANGE.match(ch):
        return 'indic'
    if (
        _DEVANAGARI.match(ch)
        or _BENGALI.match(ch)
        or _MYANMAR.match(ch)
        or _GEORGIAN.match(ch)
        or _ETHIOPIC.match(ch)
        or _KHMER.match(ch)
    ):
        return 'indic'
    if _LATIN_LETTER.match(ch):
        return 'latin'
    if unicodedata.category(ch) in ('Lo', 'Lm') and ord(ch) < 0x0370:
        return 'latin'
    # Fallback: basic ASCII Latin
    if 'a' <= ch.lower() <= 'z':
        return 'latin'
    return 'other'


def _dominant_script_from_user_text(sample: str) -> tuple[str, Counter]:
    letters = _letter_chars(sample)
    if not letters:
        return 'unknown', Counter()
    ctr: Counter = Counter()
    for c in letters:
        b = _script_bucket(c)
        if b:
            ctr[b] += 1
    if not ctr:
        return 'unknown', ctr
    top, n = ctr.most_common(1)[0]
    total = sum(ctr.values())
    ratio = n / max(total, 1)
    # Require a minimum share so mixed snippets don’t flip script randomly
    if ratio < 0.12 and len(ctr) > 2:
        return 'mixed', ctr
    return top, ctr


ReplyLang = Literal[
    'tr',
    'en',
    'ru',
    'latin_generic',
    'zh',
    'ja',
    'ko',
    'ar',
    'he',
    'th',
    'indic',
    'el',
    'other',
]


@dataclass(frozen=True)
class ReplyLanguageProfile:
    code: ReplyLang
    """Linguistic + script hint for prompts and sanitization."""

    label_short: str
    """Short label for task prompts (English, for JSON/task models)."""

    script_hint: str
    """Dominant script bucket from the user message ('latin', 'han', 'arabic', …)."""


def detect_reply_language_profile(text: str | None) -> ReplyLanguageProfile:
    """
    Infer reply language/script from the user's last message.
    Uses dominant script first (works for non-Latin languages), then TR/EN/RU heuristics for Latin/Cyrillic.
    """
    if not text or not str(text).strip():
        return ReplyLanguageProfile('other', 'match the user', 'unknown')

    sample = str(text).strip()[:12000]
    letters = _letter_chars(sample)
    if not letters:
        return ReplyLanguageProfile('other', 'match the user', 'unknown')

    dom, _ctr = _dominant_script_from_user_text(sample)
    letter_n = len(letters)

    # --- Non-Latin scripts (user wrote in that script) ------------------------------
    if dom == 'hangul':
        return ReplyLanguageProfile('ko', 'Korean', 'hangul')
    if dom == 'arabic':
        return ReplyLanguageProfile('ar', 'Arabic', 'arabic')
    if dom == 'hebrew':
        return ReplyLanguageProfile('he', 'Hebrew', 'hebrew')
    if dom == 'thai':
        return ReplyLanguageProfile('th', 'Thai', 'thai')
    if dom == 'greek':
        return ReplyLanguageProfile('el', 'Greek', 'greek')
    if dom == 'indic' or dom == 'lao':
        return ReplyLanguageProfile('indic', 'the same language as the user (Indic/SEA script)', 'indic')

    if dom in ('han', 'kana') or dom == 'mixed':
        # Japanese: kana present with han, or mostly kana
        kana_n = sum(1 for c in letters if _HIRAGANA.match(c) or _KATAKANA.match(c))
        han_n = sum(1 for c in letters if _CJK.match(c))
        if kana_n >= 1 and (kana_n + han_n) >= 2:
            return ReplyLanguageProfile('ja', 'Japanese', 'japanese')
        if han_n >= 2 or (dom == 'han' and han_n >= 1):
            return ReplyLanguageProfile('zh', 'Chinese', 'cjk')
        if kana_n >= 2:
            return ReplyLanguageProfile('ja', 'Japanese', 'japanese')

    # --- Cyrillic (Russian, Ukrainian, Bulgarian, …) ------------------------------
    cyr = sum(1 for c in letters if _CYRILLIC.match(c))
    cyr_ratio = cyr / max(letter_n, 1)
    if cyr >= 2 and (cyr_ratio >= 0.18 or (letter_n <= 24 and cyr_ratio >= 0.12)):
        return ReplyLanguageProfile('ru', 'Russian', 'cyrillic')

    lat = sum(1 for c in letters if 'a' <= c.lower() <= 'z')
    tr_spec = sum(1 for c in sample if c in _TR_SPECIAL)
    lat_ratio = lat / max(letter_n, 1)

    tr_sub = _turkish_substring_hints(sample)
    tr_rx = bool(_TR_HINTS.search(sample))
    en_matches = _EN_COMMON.findall(sample)
    en_hits = len(en_matches)
    ru_latin = bool(_RU_LATIN_HINTS.search(sample))

    if tr_spec > 0 or tr_sub or tr_rx:
        if tr_spec == 0 and not tr_sub:
            if en_hits >= 3 or (
                len(sample) < 120
                and en_hits >= 2
                and bool(re.search(r'\b(how|what|when|where|why|who)\b', sample, re.I))
            ):
                return ReplyLanguageProfile('en', 'English', 'latin')
        return ReplyLanguageProfile('tr', 'Turkish', 'latin')

    if ru_latin and lat_ratio >= 0.5 and cyr == 0:
        return ReplyLanguageProfile('ru', 'Russian', 'cyrillic')

    if en_hits >= 2 or (
        lat_ratio >= 0.5
        and len(sample) < 100
        and re.search(r'\b(how|what|when|where|why|who|which|is|are|can|do|does|please)\b', sample, re.I)
    ):
        return ReplyLanguageProfile('en', 'English', 'latin')

    # Do not map all-Latin text to English — French, German, Spanish, etc. stay latin_generic.

    # Latin extended / French / Spanish / German / …
    if dom == 'latin' or _LATIN_LETTER.search(sample):
        return ReplyLanguageProfile('latin_generic', 'the same language as the user (Latin script)', 'latin')

    return ReplyLanguageProfile('other', 'the same language as the user', dom if dom != 'unknown' else 'mixed')


def _turkish_substring_hints(s: str) -> bool:
    low = s.lower()
    needles = (
        ' için ',
        ' nasıl ',
        ' nerede ',
        ' kaç ',
        ' nereli',
        ' doğdu',
        ' dogdu',
        ' değil ',
        ' degil ',
        ' türk',
        ' turk ',
        ' bir ',
        ' ve ',
        ' mi?',
        ' mı?',
    )
    return any(n in low for n in needles)


def build_output_language_system_instruction(last_user_text: str | None) -> str:
    """Short mandatory block appended to the first system message."""
    prof = detect_reply_language_profile(last_user_text)

    bodies: dict[ReplyLang, str] = {
        'ru': (
            'Отвечай полностью на русском языке. Основной связный текст — на кириллице; латиницу используй только там, '
            'где она уместна по смыслу: URL, фрагменты кода, международные обозначения, привычные написания имён собственных '
            'и аббревиатур. Не вставляй в обычный текст символы из «чужих» систем письма (китайская, японская, корейская, '
            'арабская, иврит, тайская и т. п.), если это не часть цитируемого кода или адреса. Не копируй дословно длинные '
            'фрагменты с иностранных сайтов — перескажи, адаптируй и сформулируй по-русски. Не порождай бессмысленные '
            'последовательности символов, «ломаную» кириллицу и подобие mojibake. Соблюдай единый стиль: один язык и одна '
            'основная система письма для связного ответа.\n'
            'English: Reply entirely in Russian (Cyrillic for prose). Latin only for URLs, code, or conventional Latin '
            'proper names. No unrelated scripts in running text. Paraphrase sources; avoid mixed-script clutter.'
        ),
        'tr': (
            'Kullanıcının son mesajında geçen kişi adları, yer adları, markalar ve özel yazımlar, kullanıcının yazdığı '
            'Türkçe harflerle AYNEN korunmalıdır (ç, ğ, ı, ö, ş, ü ve büyük İ; harfleri ASCII karşılıklarına indirgeme, '
            'sessizce değiştirme veya web’de gördüğün başka bir ünlünün yazımıyla ikame etme). Web araması farklı bir yazım '
            'veya başka bir kişiyi gösteriyorsa bunu kısaca belirt; yine de kullanıcının yazdığı metni referans al. '
            'Yanıtın tamamını Türkçe yaz; yalnızca Latin tabanlı Türkçe harfleri, rakamlar ve normal noktalama kullan. '
            'Çince, Japonca, Korece, Arapça, Kiril veya başka alfabelerden karakterleri gövde metne ekleme. Kaynak metinleri '
            'aynen yapıştırma; gerekiyorsa Türkçeye çevirerek veya özetleyerek aktar. Tek dil, tutarlı yazım; anlamsız Unicode '
            'veya mojibake üretme.'
        ),
        'en': (
            'Write the entire reply in English only—do not answer in Turkish or any other language for the main text '
            '(unless the user explicitly asked for translation or bilingual output). Use standard Latin letters (a–z, A–Z), '
            'conventional punctuation, and digits for ordinary prose. Within one reply, keep one consistent variety of '
            'English (for example US or UK) for spelling and vocabulary unless the user explicitly asks otherwise. Do not '
            'insert characters from unrelated writing systems into running text (for example Chinese, Japanese, Korean, '
            'Arabic, Hebrew, Cyrillic, Thai, Devanagari). Do not paste long raw snippets from foreign-language web pages; '
            'paraphrase, summarize, or translate into English. Preserve the user’s spelling of names and terms when they '
            'wrote them in Latin letters. Avoid mojibake, decorative Unicode noise, and meaningless mixed-script clutter.'
        ),
        'latin_generic': (
            'Reply entirely in the same natural language as the user’s last message. Infer that language from vocabulary '
            'and grammar (not from the UI locale or retrieved snippets): if the user wrote English, answer fully in English '
            '— do not use Turkish for the main text. If French, in French; and so on. Use only the correct alphabet and '
            'orthography for that language: Latin letters '
            'with all diacritics and regional characters that language requires (for example é, è, ñ, ü, ö, ä, å, ą, ę, č, '
            'ř, ő, ß, and similar, as appropriate). Do not inject unrelated writing systems into ordinary prose (for '
            'example Chinese, Arabic, Cyrillic, Greek, Hebrew). Do not paste long verbatim foreign snippets; rephrase in '
            'the user’s language. Keep one coherent language and spelling style for the whole answer. Latin may still '
            'appear in URLs, code, and conventional international forms of proper names when needed.'
        ),
        'zh': (
            '请全程使用与用户最后一轮消息相同的自然语言书写（以规范现代汉语书面语为主）。正文以汉字为主，配合该语境所需的中文标点与阿拉伯数字；'
            '除网址、代码片段、必要时保留的外文人名或国际通用符号外，不要随意在正文里混入西里尔字母、阿拉伯字母、天城文、谚文、假名等与汉语语境无关的文字。'
            '不要将外文网页大段原样粘贴；请用汉语转述、概括或翻译。保持单一语言与书写系统，避免出现乱码、无意义的符号堆砌或来源页的混杂字符。\n'
            'English: Single language (Chinese for prose); unrelated scripts only where technically necessary (URLs, code, '
            'names); paraphrase sources; no mixed-script garbage.'
        ),
        'ja': (
            'ユーザーの最後の発話と同じ自然言語（日本語）で、一貫して応答してください。本文は漢字・ひらがな・カタカナ、および必要に応じた '
            '欧文（URL、コード、固有名の慣用表記など）に限定し、アラビア文字・キリル文字・ハングルなど別の文字体系を本文に無闇に混在させないでください。'
            '外国語のウェブ文章を長くそのまま貼り付けず、日本語で要約・言い換え・翻訳してください。文字化けや意味のない混在を避け、読みやすい一文一文化を保ってください。\n'
            'English: Japanese (kanji/kana + Latin only for URLs/code/conventional Latin spellings) for prose; paraphrase '
            'sources; no unrelated scripts in ordinary text.'
        ),
        'ko': (
            '사용자의 마지막 메시지와 같은 자연어(한국어)로만 일관되게 답변하세요. 본문은 한글과 필요한 경우에 한한 한자만 사용하고, '
            '아랍 문자·키릴 문자·히브리 문자 등 다른 문자 체계를 본문에 불필요하게 끼워 넣지 마세요. URL·코드·관례적인 고유명 표기에 필요한 '
            '라틴 문자는 예외로 할 수 있습니다. 외국어 원문을 길게 그대로 붙여 넣지 말고 한국어로 요약·번역·바꿔 쓰기 하세요. 한 가지 언어와 '
            '문자 체계를 유지하고, 깨진 문자나 무의미한 혼용을 피하세요.\n'
            'English: Korean (Hangul + Han as needed) for prose; Latin for URLs/code/names when conventional; paraphrase '
            'sources; no unrelated scripts in running text.'
        ),
        'ar': (
            'أجب بالكامل بلغة المستخدم العربية، باستخدام الحروف العربية للنص الأساسي. لا تخلط في الجملة نفسها بين أحرف '
            'من أنظمة كتابة مختلفة دون حاجة (لا صينية ولا كيريلية ولا يابانية ولا كورية… في النثر العادي). لا تلصق مقاطع '
            'أجنبية خاماً من الإنترنت؛ أعد صياغتها بالعربية. يُسمح باللاتينية في الروابط والأكواد والأسماء المعتادة إذا لزم '
            'الأمر.\n'
            'English: Arabic script for prose; Latin for URLs, code, and conventional Latin names when needed; paraphrase '
            'sources; no unrelated scripts in ordinary text.'
        ),
        'he': (
            'השב לאורך כל התשובה בשפה הטבעית של המשתמש (עברית), בכתב עברי לטקסט השוטף. אל תערבב כתבים זרים (קירילי, ערבי, '
            'סיני, יפני, קוריאני וכדומה) בלי צורך אמיתי. מותר להשתמש בלטינית לכתובות אינטרנט, קוד, ושמות מקובלים בלטינית. '
            'אל תדביק קטעים זרים ארוכים מאתרי אינטרנט; נסח מחדש בעברית ברורה. שמור על שפה אחת בעברית וללא «רעש» של תווים מעורבים.\n'
            'English: Hebrew script for prose; Latin for URLs, code, and conventional Latin names when needed; paraphrase '
            'sources.'
        ),
        'th': (
            'ตอบให้ครบถ้วนในภาษาเดียวกับข้อความล่าสุดของผู้ใช้ (ภาษาไทย) โดยใช้อักษรไทยและเครื่องหมายวรรคตอนที่เหมาะสมเป็นหลัก '
            'สำหรับ URL รหัส หรือชื่อที่เขียนด้วยตัวอักษรอื่นตามความจำเป็นอนุญาต อย่าแทรกอักษรจากระบบอื่น (จีน ญี่ปุ่น เกาหลี '
            'อาหรับ ซิริลลิก ฯลฯ) ลงในประโยคปกติโดยไม่จำเป็น อย่าคัดลอกข้อความภาษาอื่นยาวๆ จากเว็บมาวางติดๆ กัน — ให้สรุปหรือถอดความเป็นภาษาไทย '
            'หลีกเลี่ยงอักขระผสมแปลกๆ และข้อความเพี้ยนๆ\n'
            'English: Thai script for main text; paraphrase sources; unrelated scripts only in URLs/code/names when needed.'
        ),
        'indic': (
            'Reply entirely in the same natural language and primary writing system as the user’s last message (for example '
            'Devanagari for Hindi or Marathi, Bengali script for Bengali, Tamil script for Tamil, Gurmukhi for Punjabi, '
            'Sinhala script for Sinhala, and so on—match the user). Use only characters appropriate to that language’s '
            'standard orthography. Do not inject unrelated systems (Cyrillic, CJK, Arabic, Latin) into ordinary prose unless '
            'that language conventionally mixes them or the user clearly does so. Do not paste long raw foreign snippets; '
            'paraphrase in the user’s language. Keep the reply readable and script-consistent.'
        ),
        'el': (
            'Απάντησε πλήρως στα ελληνικά, χρησιμοποιώντας το ελληνικό αλφάβητο για το κύριο κείμενο. Μην εισάγεις χωρίς '
            'λόγο συστήματα γραφής ξένα προς τα ελληνικά (π.χ. κινεζικά, κυριλλικά, αραβικά). Μην επικολλάς αυτούσια μεγάλα '
            'αποσπάσματα από ξένες ιστοσελίδες· παράφρασε στα ελληνικά. Επιτρέπεται λατινική γραφή για URL, κώδικα και '
            'συνηθισμένα ονόματα με λατινικούς χαρακτήρες όπου χρειάζεται.\n'
            'English: Greek script for prose; Latin for URLs, code, and conventional Latin names; paraphrase sources.'
        ),
        'other': (
            'Use exactly one natural language and one primary writing system for the entire reply, aligned with the user’s '
            'last message (same language and script family). Do not mix unrelated alphabets in running text or paste long '
            'verbatim multilingual blobs from web sources; summarize or paraphrase in the user’s language. Latin may appear '
            'in URLs, code blocks, and conventional international spellings of proper names when appropriate. Avoid mojibake '
            'and meaningless character salad.'
        ),
    }

    body = bodies.get(prof.code, bodies['other'])

    global_rule = (
        '**Rule #1:** The entire reply must be in the **same natural language** as the user’s latest message—the language '
        'they actually wrote in. If that message is **English**, write **only in English** (no Turkish or other language '
        'in the main answer). Do **not** switch to the app/UI language, the model’s default locale, or the language of '
        'web search / RAG snippets unless that language matches the user’s message. Infer language only from the user’s '
        'words and script; retrieved context in another language must be translated or summarized into the user’s language.'
    )

    return (
        f'{OUTPUT_LANGUAGE_LOCK_MARKER}\n'
        f'### Output language (mandatory)\n'
        f'{global_rule}\n'
        f'{body}\n'
        f'- Proper nouns and user-typed spellings must match the user’s message (including language-specific letters).\n'
        f'- Unless the user explicitly asks for bilingual output, do not mix languages or scripts.\n'
        f'- Never answer in Turkish when the user wrote in English (or switch languages arbitrarily); match the user’s message language.'
    )


def _any_system_message_contains(messages: list[dict] | None, marker: str) -> bool:
    for m in messages or []:
        if m.get('role') != 'system':
            continue
        c = m.get('content')
        if isinstance(c, str) and marker in c:
            return True
        if isinstance(c, list):
            blob = ''
            for p in c:
                if isinstance(p, dict) and p.get('type') in ('text', 'input_text'):
                    blob += p.get('text') or ''
            if marker in blob:
                return True
    return False


def build_turkish_orthography_followup_block(last_user_text: str) -> str:
    """Quoted reference so the model keeps ç ğ ı İ ö ş ü exactly as the user typed."""
    q = ' '.join(last_user_text.strip().split())
    if len(q) > 500:
        q = q[:497] + '...'
    return (
        f'{TURKISH_ORTHOGRAPHY_MARKER}\n'
        '### Kullanıcının yazımı (zorunlu)\n'
        'Bu turda kullanıcının yazdığı metin (kişi adları ve Türkçe harfler dahil) aşağıdadır; '
        'yanıtta bu yazımı aynen koru:\n'
        f'«{q}»\n'
        'Web veya kaynakta başka bir yazım görünsen bile, kullanıcının yazdığı adı başka bir kişinin yazımıyla '
        'değiştirme; aynı kişi değilse kısaca ayır. ç/ğ/ı/ö/ş/ü harflerini ASCII veya başka harflerle değiştirme.'
    )


def maybe_append_turkish_orthography_hint(messages: list[dict] | None, last_user_text: str | None) -> list[dict]:
    """Extra system block for Turkish messages with special letters — reduces wrong name substitution from web."""
    from open_webui.utils.misc import add_or_update_system_message

    if not messages or not last_user_text:
        return messages or []
    if os.environ.get('TURKISH_ORTHOGRAPHY_HINT_ENABLED', 'true').lower() != 'true':
        return messages
    if not any(c in _TR_SPECIAL for c in last_user_text):
        return messages
    prof = detect_reply_language_profile(last_user_text)
    if prof.code != 'tr':
        return messages
    if _any_system_message_contains(messages, TURKISH_ORTHOGRAPHY_MARKER):
        return messages
    return add_or_update_system_message(
        build_turkish_orthography_followup_block(last_user_text),
        messages,
        append=True,
    )


def inject_output_language_lock(messages: list[dict] | None) -> list[dict]:
    """Append language lock + optional Turkish orthography reference (idempotent). Mutates messages in place."""
    from open_webui.utils.mws_gpt.registry import extract_last_user_text
    from open_webui.utils.misc import add_or_update_system_message

    if not messages:
        return messages or []

    ut = extract_last_user_text(messages)

    if os.environ.get('OUTPUT_LANGUAGE_LOCK_ENABLED', 'true').lower() == 'true':
        if not _any_system_message_contains(messages, OUTPUT_LANGUAGE_LOCK_MARKER):
            instr = build_output_language_system_instruction(ut)
            messages = add_or_update_system_message(instr, messages, append=True)

    return maybe_append_turkish_orthography_hint(messages, ut)


def append_task_language_footer(template: str, messages: list[dict] | None) -> str:
    """Append a compact language rule block for title/follow-up/query task prompts."""
    prof = detect_reply_language_profile(get_last_user_text_from_messages(messages))
    return (
        f'{template.rstrip()}\n\n### Language rule (mandatory)\n'
        f'- Write only in **{prof.label_short}**, i.e. the same language as the user’s last message—never the UI locale or '
        f'source-page language alone.\n'
        '- Use one language and the correct script; no mixed-script leakage from sources.\n'
    )


def get_last_user_text_from_messages(messages: list[dict] | None) -> str | None:
    from open_webui.utils.mws_gpt.registry import extract_last_user_text

    return extract_last_user_text(messages or []) or None


def _drop_char_for_profile(ch: str, prof: ReplyLanguageProfile) -> bool:
    """Return True if character should be removed (foreign script leakage)."""
    code = prof.code
    if code == 'other':
        hint = prof.script_hint
        if hint == 'cyrillic':
            return _drop_char_for_profile(ch, ReplyLanguageProfile('ru', '', 'cyrillic'))
        if hint in ('han', 'cjk'):
            return _drop_char_for_profile(ch, ReplyLanguageProfile('zh', '', 'cjk'))
        if hint == 'japanese':
            return _drop_char_for_profile(ch, ReplyLanguageProfile('ja', '', 'japanese'))
        if hint == 'hangul':
            return _drop_char_for_profile(ch, ReplyLanguageProfile('ko', '', 'hangul'))
        if hint == 'arabic':
            return _drop_char_for_profile(ch, ReplyLanguageProfile('ar', '', 'arabic'))
        if hint == 'hebrew':
            return _drop_char_for_profile(ch, ReplyLanguageProfile('he', '', 'hebrew'))
        if hint == 'thai':
            return _drop_char_for_profile(ch, ReplyLanguageProfile('th', '', 'thai'))
        if hint == 'greek':
            return _drop_char_for_profile(ch, ReplyLanguageProfile('el', '', 'greek'))
        if hint == 'indic':
            return _drop_char_for_profile(ch, ReplyLanguageProfile('indic', '', 'indic'))
        return _drop_char_for_profile(ch, ReplyLanguageProfile('latin_generic', '', 'latin'))

    b = _script_bucket(ch)
    if b is None:
        return False

    # Latin-target replies (TR/EN/generic Latin): drop non-Latin scripts; keep Latin + common combining marks
    if code in ('tr', 'en', 'latin_generic'):
        if unicodedata.category(ch) in ('Mn', 'Mc', 'Me') and ord(ch) < 0x3000:
            return False
        if b == 'latin':
            return False
        if b == 'other' and ord(ch) < 0x034F:
            return False
        # Drop anything that is clearly another script
        if b not in ('latin', 'other'):
            return True
        return False

    if code == 'ru':
        if b in ('cyrillic', 'latin'):
            return False
        if unicodedata.category(ch) in ('Mn', 'Mc') and ord(ch) < 0x3000:
            return False
        if b in ('han', 'hangul', 'kana', 'arabic', 'hebrew', 'thai', 'indic', 'greek'):
            return True
        return b not in ('cyrillic', 'latin', 'other')

    if code == 'zh':
        if b in ('han', 'latin'):
            return False
        if _HIRAGANA.match(ch) or _KATAKANA.match(ch):
            return False  # occasional Japanese in Chinese context
        return b in ('cyrillic', 'hangul', 'arabic', 'hebrew', 'greek', 'indic', 'thai')

    if code == 'ja':
        if b in ('han', 'kana', 'latin'):
            return False
        return b in ('cyrillic', 'hangul', 'arabic', 'hebrew', 'greek', 'indic', 'thai')

    if code == 'ko':
        if b in ('hangul', 'han', 'latin'):
            return False
        return b in ('cyrillic', 'kana', 'arabic', 'hebrew', 'greek', 'indic', 'thai')

    if code == 'ar':
        if b in ('arabic', 'latin'):
            return False
        return b in ('cyrillic', 'han', 'hangul', 'kana', 'hebrew', 'greek', 'indic', 'thai')

    if code == 'he':
        if b in ('hebrew', 'latin'):
            return False
        return b in ('cyrillic', 'han', 'hangul', 'kana', 'arabic', 'greek', 'indic', 'thai')

    if code == 'th':
        if b in ('thai', 'latin'):
            return False
        return b in ('cyrillic', 'han', 'hangul', 'kana', 'arabic', 'hebrew', 'greek', 'indic')

    if code == 'indic':
        if b in ('indic', 'latin'):
            return False
        return b in ('cyrillic', 'han', 'hangul', 'kana', 'arabic', 'hebrew', 'greek', 'thai')

    if code == 'el':
        if b in ('greek', 'latin'):
            return False
        return b in ('cyrillic', 'han', 'hangul', 'kana', 'arabic', 'hebrew', 'indic', 'thai')

    return False


def _strip_chars_for_profile(s: str, prof: ReplyLanguageProfile) -> str:
    return ''.join(ch for ch in s if not _drop_char_for_profile(ch, prof))


def _sanitize_plain_segment(text: str, last_user_text: str | None) -> str:
    """Script-profile strip only (used when OUTPUT_LANGUAGE_SANITIZE is on)."""
    prof = detect_reply_language_profile(last_user_text)
    return _strip_chars_for_profile(text, prof)


def _output_cleanup_enabled() -> bool:
    return (
        os.environ.get('OUTPUT_TOKEN_SOUP_STRIP', 'true').lower() == 'true'
        or os.environ.get('OUTPUT_LANGUAGE_SANITIZE', 'true').lower() == 'true'
    )


def _clean_plain_segment(text: str, last_user_text: str | None) -> str:
    """Token-soup strip (optional) + script strip (optional)."""
    t = text
    if os.environ.get('OUTPUT_TOKEN_SOUP_STRIP', 'true').lower() == 'true':
        t = _strip_token_soup_paragraphs(t)
    if os.environ.get('OUTPUT_LANGUAGE_SANITIZE', 'true').lower() == 'true':
        t = _sanitize_plain_segment(t, last_user_text)
    return t


def sanitize_leaked_scripts(text: str | None, last_user_text: str | None) -> str | None:
    """
    Remove characters from scripts that contradict the detected reply profile (best-effort).
    Optionally strips degenerate “token soup” paragraphs (OUTPUT_TOKEN_SOUP_STRIP, default on).
    If both OUTPUT_TOKEN_SOUP_STRIP and OUTPUT_LANGUAGE_SANITIZE are false, returns text unchanged.
    Code fences (```) are preserved.
    """
    if text is None or not isinstance(text, str) or not text:
        return text
    if not _output_cleanup_enabled():
        return text

    if '```' not in text:
        return _clean_plain_segment(text, last_user_text)

    parts = text.split('```')
    out: list[str] = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            out.append(_clean_plain_segment(part, last_user_text))
        else:
            out.append(part)
    return '```'.join(out)


def sanitize_or_aligned_output_items(output: list | None, last_user_text: str | None) -> None:
    """Mutate OR-aligned assistant output items in place."""
    if not output or not _output_cleanup_enabled():
        return

    def walk_parts(parts: list | None) -> None:
        if not parts:
            return
        for p in parts:
            if not isinstance(p, dict):
                continue
            t = p.get('type')
            if t in ('output_text', 'text', 'summary_text') and 'text' in p:
                raw = p.get('text')
                if isinstance(raw, str) and raw:
                    p['text'] = sanitize_leaked_scripts(raw, last_user_text) or raw

    for item in output:
        it = item.get('type')
        if it == 'message':
            walk_parts(item.get('content'))
        elif it == 'reasoning':
            walk_parts(item.get('content'))
            summ = item.get('summary')
            if isinstance(summ, list):
                walk_parts(summ)
