"""
MWS GPT model registry: merge fetched OpenAI-compatible model IDs with capability hints.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

Capability = Literal['text', 'code', 'vision', 'image_generation', 'audio_transcription', 'embedding']


@dataclass
class MwsModelRecord:
    id: str
    label: str
    provider: str = 'mws'
    capabilities: set[str] = field(default_factory=set)
    manual_selectable: bool = True
    is_default_for: set[Capability] = field(default_factory=set)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'label': self.label,
            'provider': self.provider,
            'capabilities': sorted(self.capabilities),
            'manualSelectable': self.manual_selectable,
            'defaultFor': sorted(self.is_default_for),
        }


def _norm_id(mid: str) -> str:
    return (mid or '').strip()


def infer_capabilities_from_model_id(model_id: str) -> set[str]:
    """Conservative heuristics when the API does not expose modalities."""
    s = model_id.lower()
    caps: set[str] = {'text'}
    if any(
        x in s
        for x in (
            'whisper',
            'audio',
            'speech',
            'transcrib',
            'stt',
            'tts',
        )
    ):
        caps.add('audio_transcription')
    if any(x in s for x in ('vision', 'vl-', '4o', 'gpt-4-turbo', 'multimodal', 'moondream', 'llava')):
        caps.add('vision')
    if any(x in s for x in ('dall', 'image', 'diffusion', 'flux', 'sdxl', 'midjourney')):
        caps.add('image_generation')
    if any(x in s for x in ('embed', 'embedding', 'text-embedding')):
        caps.add('embedding')
    if any(x in s for x in ('code', 'coder', 'deepseek-coder', 'starcoder')):
        caps.add('code')
    return caps


def build_mws_registry(
    fetched_openai_models: list[dict[str, Any]],
    env_defaults: dict[str, str | None],
) -> tuple[list[MwsModelRecord], list[str]]:
    """
    Merge GET /models results with env default IDs and inferred capabilities.
    Returns (records, warnings).
    """
    warnings: list[str] = []
    by_id: dict[str, MwsModelRecord] = {}

    for m in fetched_openai_models or []:
        mid = _norm_id(m.get('id') or m.get('name') or '')
        if not mid:
            continue
        label = m.get('name') or mid
        caps = infer_capabilities_from_model_id(mid)
        by_id[mid] = MwsModelRecord(id=mid, label=label, capabilities=caps)

    for cap in (
        'text',
        'code',
        'vision',
        'image_generation',
        'audio_transcription',
        'embedding',
    ):
        raw = env_defaults.get(cap)
        if not raw:
            continue
        eid = _norm_id(raw)
        if not eid:
            continue
        if eid not in by_id:
            by_id[eid] = MwsModelRecord(
                id=eid,
                label=eid,
                capabilities=infer_capabilities_from_model_id(eid),
            )
            warnings.append(f"MWS: default model for '{cap}' ({eid}) not in remote /models list; using env fallback.")
        by_id[eid].is_default_for.add(cap)
        by_id[eid].capabilities.update(infer_capabilities_from_model_id(eid))

    # Ensure each declared default has at least text capability for UI grouping
    for rec in by_id.values():
        if not rec.capabilities:
            rec.capabilities.add('text')

    return list(by_id.values()), warnings


def pick_fallback_model_id(
    records: list[MwsModelRecord],
    env_defaults: dict[str, str | None],
    capability: Capability,
) -> tuple[str | None, str | None]:
    """Returns (model_id, warning)."""
    # Prefer explicit env default for this capability
    raw = env_defaults.get(capability)
    if raw:
        eid = _norm_id(raw)
        ids = {r.id for r in records}
        if eid and eid in ids:
            return eid, None
        if eid:
            return eid, f"MWS: default for {capability} ({eid}) not in registry; attempting anyway."
    # Any record that lists the capability
    for r in records:
        if capability in r.capabilities:
            return r.id, None
    # Plain text fallback
    for r in records:
        if 'text' in r.capabilities:
            return r.id, None
    if records:
        return records[0].id, None
    return None, f'MWS: no models available for fallback ({capability}).'


_CODE_HINT = re.compile(
    r'\b(def |class |import |async def|fn |pub fn|const |let mut|package |func |SELECT |INSERT )\b|\bSQL\b',
    re.I,
)
# Görsel *oluşturma*: “image generation nedir?” gibi anlatım sorularını görsel moduna düşürmemek için
# tek başına “image generation” ifadesi yok; eylem + görsel veya çok dilli çiz/üret kalıpları var.
_IMG_INTENT = re.compile(
    r'\b(generate|draw|render|create|make)\b.+\b(image|picture|photo|illustration)\b'
    r'|\bdall-?e\b|\bstable diffusion\b|\bmidjourney\b|\bflux\b'
    r'|\b(çiz|resim|görsel|illüstrasyon|картин|рисунок|изображен|нарисуй|сгенерируй)\b'
    r'|\b(draw|paint|sketch)\b\s+\b(a|an|the|me)?\s*\w+',
    re.I,
)

# Kelime sınırı / ekler (çizer misin) için tam cümle kalıpları ve alt dizgi eşleşmeleri
_IMAGE_PHRASES: tuple[str, ...] = (
    'resim çiz',
    'resim üret',
    'resim oluştur',
    'resim istiyorum',
    'resim at',
    'görsel oluştur',
    'görsel üret',
    'görsel istiyorum',
    'görsel tasarla',
    'logo tasarla',
    'logo çiz',
    'logo oluştur',
    'logo üret',
    'poster yap',
    'banner tasarla',
    'draw me',
    'draw a ',
    'draw an ',
    'paint me',
    'paint a ',
    'sketch a ',
    'generate a picture',
    'generate an image',
    'create a logo',
    'make a picture',
    'make an image',
    'image of ',
    'picture of ',
)

# ASCII klavye: "ciz" (ç olmadan) — Auto çizim niyetini kaçırmaması için
_TR_CIZ_TYPO = re.compile(r'\bciz\b', re.I)


def _normalize_tr_keyboard_typos(text: str) -> str:
    if not text:
        return text
    return _TR_CIZ_TYPO.sub('çiz', text)


def _wants_image_creation(message_text: str) -> bool:
    """Auto yönlendirme: metin görsel üretim isteği mi (konuşma / logo / TR komutları)?"""
    t = _normalize_tr_keyboard_typos(message_text or '')
    if not t.strip():
        return False
    if _IMG_INTENT.search(t):
        return True
    low = t.lower()
    pad = f' {low} '
    for ph in _IMAGE_PHRASES:
        if ph in pad or ph in low:
            return True
    # Tek kelimelik kısa komutlar (başta/sonda)
    for w in ('illustrasyon', 'illustration', 'infographic'):
        if w in low:
            return True
    return False


def extract_last_user_text(messages: list[dict[str, Any]] | None) -> str:
    if not messages:
        return ''
    for m in reversed(messages):
        if m.get('role') != 'user':
            continue
        c = m.get('content')
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            parts = []
            for p in c:
                if isinstance(p, dict) and p.get('type') == 'text':
                    parts.append(p.get('text') or '')
                elif isinstance(p, dict) and p.get('type') == 'input_text':
                    parts.append(p.get('text') or '')
            return '\n'.join(parts)
    return ''


def collect_attachment_kinds(
    files: list[dict[str, Any]] | None,
    messages: list[dict[str, Any]] | None,
) -> set[str]:
    kinds: set[str] = set()
    for f in files or []:
        ct = (f.get('content_type') or f.get('type') or '').lower()
        if ct.startswith('image/'):
            kinds.add('image')
        elif ct.startswith('audio/') or ct in ('audio',):
            kinds.add('audio')
    if messages:
        for m in reversed(messages[-3:]):
            c = m.get('content')
            if isinstance(c, list):
                for p in c:
                    if not isinstance(p, dict):
                        continue
                    t = p.get('type', '')
                    if t == 'image_url' or t == 'image':
                        kinds.add('image')
                    if t in ('input_audio', 'audio'):
                        kinds.add('audio')
    return kinds


def should_inject_web_search_for_message(
    *,
    message_text: str,
    attachments: set[str],
    input_mode: str | None,
) -> bool:
    """
    MWS: pipeline'a zorunlu web/RAG enjeksiyonu — çizim isteklerinde kapatılır;
    diğerlerinde 'smart' modda yalnızca güncel veri / açık araştırma niyeti vb.
    MWS_WEB_SEARCH_INJECT_MODE=always|never|smart (varsayılan smart).
    """
    import os

    mode = (os.environ.get('MWS_WEB_SEARCH_INJECT_MODE') or 'smart').strip().lower()
    modality, _ = classify_task_modality(
        message_text=message_text,
        attachments=attachments,
        input_mode=input_mode,
    )
    if modality == 'image_generation':
        return False
    if mode == 'never':
        return False
    if mode == 'always':
        return True

    t_raw = message_text or ''
    t = t_raw.strip().lower()
    if not t:
        return False

    # Zaman / saat dilimi — taze bilgi mantıklı
    if re.search(
        r'\b(saat|what time|which time|timezone|utc|gmt|zaman dilimi|yerel saat|kaçta)\b',
        t_raw,
        re.I,
    ):
        return True
    if re.search(r'\btime in\b', t_raw, re.I):
        return True
    if re.search(r'\bhour\b.+\b(in|at|for)\b', t_raw, re.I):
        return True

    # Açık internet / güncellik / finans / hava
    if any(
        k in t
        for k in (
            'araştır',
            'araştırma',
            'internetten',
            "web'de",
            'web de',
            'googla',
            'google',
            'kaynak bul',
            'kaynak göster',
            'kaynaklar',
            'haber',
            'güncel',
            'son dakika',
            'bugün ',
            ' şu an ',
            'hava durumu',
            'weather',
            'fiyat',
            'döviz',
            'borsa',
            'kur ',
            ' dolar ',
            ' euro ',
        )
    ):
        return True
    if re.search(
        r'^\s*(kimdir|nedir|who is|what is the (latest|current)|when did|where is)\b',
        t_raw,
        re.I,
    ):
        return True
    return False


def classify_task_modality(
    *,
    message_text: str,
    attachments: set[str],
    input_mode: str | None,
) -> tuple[Capability, str]:
    """
    Deterministic routing classification for **chat completions** (assistant text reply).

    STT for uploads runs in Open WebUI's file pipeline; it must not route the main chat
    request to Whisper. Whisper/speaches is not a chat model — Auto previously picked
    whisper-turbo-local for audio attachments and caused 500 on /v1/chat/completions.
    """
    if input_mode and input_mode.lower() in ('voice', 'audio', 'call'):
        return 'text', 'input_mode_voice_or_audio'

    if 'audio' in attachments:
        # Transcript is (or will be) user message text; same as plain text chat for routing.
        if (message_text or '').strip():
            return 'text', 'audio_attachment_with_transcript'
        return 'text', 'audio_attachment_use_text_model'

    if 'image' in attachments:
        return 'vision', 'image_attachment'

    t = _normalize_tr_keyboard_typos(message_text or '')
    # Önce görsel üretim: kod modeline düşmeden (ör. mesajda "python" geçse bile) çiz/üret niyeti yakalanır.
    if _wants_image_creation(t):
        return 'image_generation', 'image_creation_intent'

    if _CODE_HINT.search(t) or '```' in t:
        return 'code', 'code_heuristic_fence_or_syntax'
    low = t.lower()
    # Sadece dil adı (ör. "Python nedir") kod modeline gitmesin; aşağıdakiler programlama bağlamı taşır.
    code_kw = (
        'write code',
        'refactor',
        'unit test',
        'stack trace',
        'exception',
        'fix bug',
        'typescript',
        'javascript',
        'java ',
        'golang',
        'rust',
        'function ',
        'class ',
        'api ',
        'debug',
        'pull request',
        'write a function',
        'unit tests',
        'python code',
        'python script',
        'javascript code',
        'typescript code',
        'sql query',
        'regex',
        'big o',
        'leetcode',
    )
    if any(k in low for k in code_kw):
        return 'code', 'code_intent_keywords'

    if any(
        k in low
        for k in (
            'create image',
            'generate image',
            'make a picture',
            'make an image',
            'görsel oluştur',
            'fotoğraf üret',
            'poster yap',
            'logo yap',
        )
    ):
        return 'image_generation', 'image_intent_phrase'

    # TR/RU: kısa görsel komutları ("araba çiz", "кот нарисуй") — _wants_image_creation kaçırdıysa yedek
    if any(
        k in low
        for k in (
            'çiz',
            'ciz',
            'resim ',
            ' resim',
            'görsel',
            'illüstrasyon',
            'нарисуй',
            'картинк',
            'изображен',
            'сгенерируй изображ',
        )
    ):
        return 'image_generation', 'image_intent_multilingual'

    return 'text', 'default_text'
