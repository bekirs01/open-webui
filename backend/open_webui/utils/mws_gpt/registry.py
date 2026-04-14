"""
MWS GPT model registry: merge fetched OpenAI-compatible model IDs with capability hints.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

Capability = Literal[
    'text',
    'code',
    'vision',
    'image_generation',
    'audio_transcription',
    'embedding',
    'export',
]


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
    'fotoğraf çiz',
    'fotoğraf üret',
    'foto çiz',
    'bana resim',
    'bana bir resim',
    'bir resim çiz',
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
    # Geçmişe atıf soruları (yeni çizim değil)
    if re.search(r'\b(?:what|which)\s+(?:image|picture|photo)\b', t, re.I) and re.search(
        r'\b(?:earlier|before|previous|last\s+time)\b', t, re.I
    ):
        return False
    low = t.lower()
    # Türkçe kısa çizim: "bana ucan at çiz" (ASCII), "uçan at çiz", "at çiz"
    if re.search(
        r'\b(?:uçan|ucan|uç|uc)\s+(?:at|kuş|kus)\s+(?:çiz|ciz)\b'
        r'|\b(?:at|kuş|kus)\s+(?:çiz|ciz)\b'
        r'|\bbana\s+(?:uçan|ucan)\s+at\b',
        low,
    ):
        return True
    if _IMG_INTENT.search(t):
        return True
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


def wants_image_edit_pipeline_turn(message_text: str) -> bool:
    """
    True when the user intends image-to-image / edit / style on an uploaded photo (not vision Q&A only).

    Used to enable chat_image_generation_handler so image_edits receives the attachment URLs from the request body.
    Actual routing still requires a resolvable source image (this turn, chat history, or DB fallback).
    """
    t = _normalize_tr_keyboard_typos((message_text or '').strip())
    if not t:
        return False
    low = t.lower()

    # Pure description / VQA on an image — do not hijack into image edit API
    if re.search(
        r'\b(?:bu|şu)\s+(?:görsel|foto|fotoğraf|resim)\w*\s+(?:içinde|de|da|ta)\s+(?:ne\s+var|kim(?:dir)?|nedir)\b',
        low,
    ):
        return False
    if re.search(
        r'^\s*(?:what|who|where|when|how\s+much|which|whose|describe|explain|açıkla|tanımla|'
        r'bu\s+nedir|nedir|kim(?:dir)?|hangi|kaç)\b',
        low,
    ) and not re.search(
        r'\b(?:çiz|ciz|draw|giydir|elbise|takım|suit|edit|düzenle|değiştir|üzerine|olarak|style|transform|'
        r'photoshop|remove|ekle|replace|arka|background|retouch|portrait|headshot|inpaint)\b',
        low,
    ):
        return False
    if re.match(r'^\s*ne\s+var\b', low) and not re.search(
        r'\b(?:değiştir|düzenle|ekle|çıkar|sil|remove|add|edit)\b', low
    ):
        return False

    # Yüksek benzerlik / referansla yeniden üret: ekteki fotoğrafa çok yakın çıktı (i2i, t2i değil)
    if re.search(
        r'(?:'
        r'benzer\s+(?:bir\s+)?(?:şey|resim|görsel|foto|fotoğraf|versiyon|kopya|hal|tablo)\w*\s*(?:çiz|yap|üret|oluştur|draw|generate|make)|'
        r'(?:çiz|draw|üret|yap|oluştur|generate|make).{0,55}(?:benzer|aynı|tıpkı|bunun\s+gibi|bu\s+foto|this\s+photo)|'
        r'bu\s+(?:fotoğraf|foto|resim|görsel)(?:a|ı|e|u)?\s+(?:çok\s+)?benzer|'
        r'bu\s+(?:fotoğraf|foto|resim|görsel).{0,40}(?:çiz|yap|üret|oluştur|draw|generate|make|istiyorum)|'
        r'(?:fotoğrafı|görseli|resmi)\s+(?:gör(?:üp)?|baz\s*al(?:arak)?|referans).{0,35}(?:çiz|yap|üret|benzer|oluştur)|'
        r'(?:aynısı|aynısından|aynı\s+şekilde|tıpkı\s+bunun\s+gibi|tıpkı\s+böyle|buna\s+göre)\s*(?:çiz|yap|üret|oluştur|istiyorum)?|'
        r'\b(?:recreate|reproduce|remake|duplicate|match\s+this|same\s+as\s+this|look\s*like\s+this|'
        r'copy\s+of\s+this|reference\s+photo|photo[\s-]*match|high[\s-]*fidelity|near[\s-]*identical)\b'
        r')',
        low,
        re.I,
    ):
        return True

    # Strong multilingual edit / manipulation intent (paired with a source image by the caller)
    if re.search(
        r'\b(?:'
        r'çiz|ciz|draw|paint|sketch|edit|düzenle|değiştir|modify|inpaint|outpaint|retouch|photoshop|'
        r'remove|delete|erase|add|replace|swap|insert|cut\s+out|recolor|recolou?r|'
        r'giydir|elbise|takım|tyakım|suit|ceket|jacket|wear|wearing|outfit|formal|'
        r'olarak\s+çiz|üzerine|üstüne|üzerinde|'
        r'bunun|buna|bunu|buna\s+göre|bu\s+foto|bu\s+resim|bu\s+fotoğraf|'
        r'this\s+image|this\s+photo|this\s+picture|'
        r'according\s+to|based\s+on\s+this|same\s+person|preserve\s+face|keep\s+face|'
        r'change\s+(?:the\s+)?(?:background|hairstyle|hair|clothes|outfit|scene|colour|color|lighting)|'
        r'(?:remove|delete)\s+(?:the\s+)?(?:background|bg|foreground|object|objects)|'
        r'background\s+removal|\bbg\s+remove\b|remove\s+bg|remove\s+background|'
        r'(?:turn|make|transform)\s+(?:this|it|him|her|that)\s+into|'
        r'(?:professional|formal|business|cinematic)\s+(?:portrait|headshot|look|photo)|'
        r'make\s+(?:it|him|her|this)\s+(?:more\s+)?(?:formal|professional|cinematic)|'
        r'make\s+(?:him|her|them)\s+wear|put\s+(?:him|her|them)\s+in|'
        r'daha\s+resmi|daha\s+sinematik|şimdi|'
        r'(?:saç|hair)\s*(?:rengini|rengi|color|colour|style)?|'
        r'arka\s*plan|arkaplan|ofis\s+yap|'
        r'çıkar|sil|kaldır|erase|'
        r'photorealistic\s+edit'
        r')\b',
        low,
        re.I,
    ):
        return True

    for ph in (
        'arka plan',
        'arkaplan',
        'remove background',
        'background remove',
        'remove the background',
        'takım elbise',
        'üzerine ceket',
        'üstüne ceket',
        'edit this image',
        'edit this photo',
        'modify this photo',
        'change the background',
        'professional headshot',
        'formal portrait',
        'buna takım',
        'bunu daha',
        'bu fotoğrafa',
        'bu fotoğrafa benzer',
        'buna benzer',
        'benzer çiz',
        'aynısından çiz',
        'bu resimde',
        'bu adama',
        'bu kadına',
        'formal yap',
        'daha resmi',
        'pixar tarzı',
        'ghibli',
        'anime tarzı',
        'anime yap',
        'stüdyo ghibli',
    ):
        if ph in low:
            return True

    # Style / scene transfer on the attached photo (not pure VQA)
    if re.search(
        r'\b(?:'
        r'pixar|ghibli|disney|anime|manga|cartoon\s+style|stylize|style\s*transfer|'
        r'plajda|sahilde|at\s+the\s+beach|in\s+the\s+office|replace\s+(?:the\s+)?background|'
        r'arka\s*plan[ıi]?\s+(?:değiştir|değiş|çevir|koy)|'
        r'(?:make|turn)\s+it\s+(?:pixar|anime|cartoon)|'
        r'(?:bunu|şunu)\s+(?:pixar|anime|çizgi\s+film)'
        r')\b',
        low,
        re.I,
    ):
        return True

    # Russian: dress / change / background
    if re.search(
        r'(?:^|[\s,.;!?])(?:измени|изменить|надень|смени|убери|добавь|удали|сделай|поменяй)\b',
        t,
        re.I,
    ) or re.search(
        r'\b(?:костюм|пиджак|фон|фона|портрет|лицо|одежд|фото|изображен)\w*\b',
        t,
        re.I,
    ):
        return True

    # Arabic script: change / add / remove / background / image
    if re.search(
        r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]{3,}',
        message_text or '',
    ) and re.search(
        r'(?:غيّر|غير|أضف|ازل|احذف|خلفية|صورة|شخص|ملابس|بدلة|إزالة)',
        message_text or '',
    ):
        return True

    return False


def collect_attachment_kinds(
    files: list[dict[str, Any]] | None,
    messages: list[dict[str, Any]] | None,
) -> set[str]:
    kinds: set[str] = set()
    for f in files or []:
        ct = (f.get('content_type') or f.get('type') or '').lower()
        if ct.startswith('image/') or f.get('type') == 'image':
            kinds.add('image')
        elif ct.startswith('audio/') or ct in ('audio',):
            kinds.add('audio')
        elif (
            'pdf' in ct
            or ct.startswith('application/pdf')
            or ct in ('application/vnd.openxmlformats-officedocument.wordprocessingml.document',)
            or f.get('type') in ('file', 'document')
        ):
            kinds.add('document')
    # Recent turns only (not full history): follow-up edits reference images from a few messages back.
    if messages:
        tail = messages[-16:] if len(messages) > 16 else messages
        for m in reversed(tail):
            for f in m.get('files') or []:
                if not isinstance(f, dict):
                    continue
                ct = (f.get('content_type') or f.get('type') or '').lower()
                if f.get('type') == 'image' or ct.startswith('image/'):
                    kinds.add('image')
                elif ct.startswith('audio/'):
                    kinds.add('audio')
                elif (
                    'pdf' in ct
                    or ct.startswith('application/pdf')
                    or f.get('type') in ('file', 'document')
                ):
                    kinds.add('document')
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


_SUPPLEMENTAL_WEB_AFTER_URL_RE = re.compile(
    r'(?:'
    r'başka\s+kaynak|diğer\s+kaynak|ek\s+kaynak|karşılaştır|çapraz\s+kontrol|'
    r'internetten\s+de|web\s*[\'’]?(?:de)?\s+ara|araştır(?:ıp)?|'
    r'resmi\s+kaynak(?:ı|ları)?\s+bul|doğrula(?:y(?:ıp|arak))?|'
    r'(?:also|additionally)\s+(?:search|verify|confirm)|cross[\s-]?check|'
    r'other\s+sources|additional\s+sources'
    r')',
    re.IGNORECASE,
)


def supplemental_web_research_requested(message_text: str) -> bool:
    """
    URL sayfa metni enjekte edildi ama kullanıcı ek web araştırması da istiyor — web_search bastırma.
    """
    if not (message_text or '').strip():
        return False
    return bool(_SUPPLEMENTAL_WEB_AFTER_URL_RE.search(message_text))


def wants_web_research_heavy_task(message_text: str) -> bool:
    """
    True when the user likely needs real web retrieval (links, official pages, verification, fresh facts).

    Used by Auto text routing (bump complexity) and by should_inject_web_search_for_message (smart mode).
    Keep in sync with URL-fetch flows: URL-only summarize should rely on fetch, not duplicate search.
    """
    t = (message_text or '').strip()
    if not t:
        return False
    low = t.lower()

    # Direct link / official source / registration intent (TR + EN + RU)
    if re.search(
        r'(?:'
        r'link\s*(?:ver|için|bul|atar\s*mısın|paylaş|gönder)|linki\s+ver|doğrudan\s+link|'
        r'url\s+ver|adres\s+ver|hyperlink|'
        r'resmi\s+(?:site|web|sayfa|kaynak|başvuru)|resm[iî]\s+siteden|'
        r'official\s+(?:website|site|page|source)|primary\s+source|'
        r'başvuru\s+(?:sayfası|linki|formu|ekranı)|kayıt\s+(?:sayfası|linki|formu)|'
        r'admissions|enrollment|apply\s+online|application\s+link|'
        r'nereden\s+başvur|nasıl\s+kayıt|kayıt\s+ol(?:ur)?um|where\s+to\s+apply|how\s+to\s+register|'
        r'doğrula|kontrol\s+et|teyit\s+et|doğrulay|verify|fact[\s-]?check|cross[\s-]?check|'
        r'son\s+durum|güncel\s+(?:bilgi|durum|veri|haber)|en\s+son\s+(?:bilgi|durum)|'
        r'(?:bugün|şu\s*an|şu\s+an|right\s*now)\b|up[\s-]?to[\s-]?date|latest\s+(?:status|news|info)|'
        r'(?:şu|bu)\s+kişinin\s+(?:sitesi|web\s*sitesi|resmi\s+sitesi)|'
        r'find\s+(?:the\s+)?(?:official\s+)?website|official\s+URL|'
        # Rusça
        r'официальный\s+сайт|найди\s+сайт|ссылк[аеу]\s+(?:дай|скинь|найди)|'
        r'актуальн\w+\s+информац|последн\w+\s+(?:новост|данн|информац)|'
        r'проверь|уточни|найди\s+в\s+интернете|поищи\s+в\s+(?:интернете|сети)|'
        r'загугли|погугли|'
        r'где\s+(?:можно|найти|купить|скачать|посмотреть)|'
        r'как\s+(?:зарегистрироваться|подать\s+заявку|записаться)'
        r')',
        low,
        re.I,
    ):
        return True

    # Loose keyword combos (avoid firing on every "site" mention)
    if re.search(
        r'\b(?:kaynak|source|источник)\b.{0,80}\b(?:göster|bul|iste|ver|cite|link|покаж|найд|дай)\b',
        message_text or '',
        re.I,
    ):
        return True
    return False


def should_inject_web_search_for_message(
    *,
    message_text: str,
    attachments: set[str],
    input_mode: str | None,
    research_grounded_image: bool = False,
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
        # Real-world draw requests need web facts before image gen (see image_grounding.py).
        if research_grounded_image and mode != 'never':
            return True
        return False
    if is_pure_image_draw_turn(message_text, attachments, input_mode):
        return False
    if mode == 'never':
        return False
    if mode == 'always':
        return True

    try:
        from open_webui.utils.mws_gpt.export_intent import export_intent_blocks_web_search

        if export_intent_blocks_web_search(message_text or ''):
            return False
    except Exception:
        pass

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

    # Açık internet / güncellik / finans / hava — TR + EN + RU
    if any(
        k in t
        for k in (
            # Türkçe
            'araştır',
            'araştırma',
            'internetten',
            'internette',
            'internet',
            "web'de",
            'web de',
            'webde',
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
            'bak ',
            'bul ',
            'ara ',
            'arat',
            # İngilizce
            'search',
            'look up',
            'find out',
            'browse',
            'look for',
            'search for',
            'search the',
            'search online',
            'search on',
            'on the internet',
            'from the internet',
            'latest news',
            'current price',
            'stock price',
            # Rusça
            'интернет',
            'поиск',
            'поищи',
            'погугли',
            'загугли',
            'найди',
            'ищи',
            'в интернете',
            'в сети',
            'новости',
            'актуальн',
            'последни',
            'свежи',
            'курс ',
            'погода',
            'цена',
            'биржа',
            'валюта',
        )
    ):
        return True
    if re.search(
        r'^\s*(kimdir|nedir|who is|what is the (latest|current)|when did|where is|кто так|что так|когда)\b',
        t_raw,
        re.I,
    ):
        return True
    if wants_web_research_heavy_task(t_raw):
        return True
    return False


_MEMORY_CONTEXT_PATTERN = re.compile(
    r'(?:'
    r'(?:benim|my)\s+(?:adım|ismim|name)|'
    r'(?:daha\s+önce|demin|önceki|geçen|son|earlier|before|previous|last)\s+'
    r'(?:ne|what|hangi|which|konuş|söyle|anlat|sor|yaptı|çizdi|yazdı|said|asked|drew|wrote|created|discussed)|'
    r'(?:ne\s+(?:resim|görsel|resmi|image|picture))\s+(?:çizdin|yaptın|ürettin|oluşturdun|drew|created|generated)|'
    r'(?:hatırlıyor\s+musun|remember|recall|do\s+you\s+remember)|'
    r'(?:önceki|previous|earlier|last|son)\s+(?:sohbet|konuşma|chat|conversation|message|mesaj|cevap|answer)|'
    r'(?:az\s+önce|just\s+now|demin)\s+(?:ne|what)|'
    r'devam\s+et|continue\s+from|'
    r'(?:sana|senden)\s+(?:ne\s+)?(?:sordum|istedim|söyledim)|'
    r'(?:what|ne)\s+(?:did\s+)?(?:i|ben)\s+(?:ask|sor|say|söyle|request|iste)'
    r')',
    re.I,
)

_IMAGE_REFERENCE_NOT_CREATION = re.compile(
    r'(?:'
    r'(?:ne|hangi|which|what)\s+(?:resim|görsel|image|picture)|'
    r'(?:resim|görsel|image|picture)\s+(?:çizdin|yaptın|gösterdin|drew|created|showed)|'
    r'(?:önceki|demin|daha\s+önce|earlier|before|previous)\s+(?:resim|görsel|image|picture|çiz)'
    r')',
    re.I,
)


def _is_memory_or_context_question(text: str) -> bool:
    """True when the user is asking about previous conversation, not requesting new generation."""
    if not text:
        return False
    if _MEMORY_CONTEXT_PATTERN.search(text):
        return True
    if _IMAGE_REFERENCE_NOT_CREATION.search(text):
        if not _wants_image_creation(text):
            return True
        # "demin ne resmi çizdin" has both patterns but is a reference question
        if re.search(r'(?:ne|what|hangi).{0,30}(?:çizdin|drew|created|yaptın)', text, re.I):
            return True
    return False


def classify_task_modality(
    *,
    message_text: str,
    attachments: set[str],
    input_mode: str | None,
    enable_image_edit: bool = False,
    routing_text: str | None = None,
) -> tuple[Capability, str]:
    """
    Deterministic routing classification for **chat completions** (assistant text reply).

    Layer 1: Hard deterministic rules (attachments, input mode, memory/context)
    Layer 2: Intent keywords (image creation, code, export)

    STT for uploads runs in Open WebUI's file pipeline; it must not route the main chat
    request to Whisper. Whisper/speaches is not a chat model — Auto previously picked
    whisper-turbo-local for audio attachments and caused 500 on /v1/chat/completions.
    """
    if input_mode and input_mode.lower() in ('voice', 'audio', 'call'):
        return 'text', 'input_mode_voice_or_audio'

    t = _normalize_tr_keyboard_typos(routing_text or message_text or '')

    # LAYER 1A: Memory/context questions MUST go to text, NEVER image_generation
    if _is_memory_or_context_question(t):
        return 'text', 'memory_or_context_question'

    try:
        from open_webui.utils.mws_gpt.export_intent import resolve_export_intent

        if resolve_export_intent(t):
            return 'export', 'export_conversion_intent'
    except Exception:
        pass

    # PDF / office docs — extraction + summarization uses text/reasoning models (not image gen)
    if 'document' in attachments:
        return 'text', 'document_attachment'

    # LAYER 1B: Attachment-based routing
    if 'audio' in attachments:
        if (message_text or '').strip():
            return 'text', 'audio_attachment_with_transcript'
        return 'text', 'audio_attachment_use_text_model'

    if 'image' in attachments:
        try:
            from open_webui.utils.mws_gpt.export_intent import resolve_export_intent

            if resolve_export_intent(t):
                return 'export', 'export_with_image_attachment'
        except Exception:
            pass
        if enable_image_edit and wants_image_edit_pipeline_turn(t):
            return 'image_generation', 'image_edit_intent_with_attachment'
        return 'vision', 'image_attachment'

    # LAYER 2: Intent-based classification (no attachments)
    if _wants_image_creation(t):
        return 'image_generation', 'image_creation_intent'

    if '```' in t:
        return 'code', 'code_heuristic_fence'
    if _CODE_HINT.search(t) and len(t) > 30:
        return 'code', 'code_heuristic_syntax'
    low = t.lower()
    _code_action_kw = (
        'write code',
        'fix this code',
        'refactor',
        'unit test',
        'stack trace',
        'exception',
        'fix bug',
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
        'kod yaz',
        'kodu düzelt',
        'fonksiyon yaz',
        'hata düzelt',
        'bug düzelt',
        'kod oluştur',
    )
    if re.search(r'\b(?:bu\s+)?(?:python\s+|javascript\s+|typescript\s+)?kodu(?:nu)?\s+düzelt\b', low, re.I):
        return 'code', 'code_fix_turkish'
    if any(k in low for k in _code_action_kw):
        return 'code', 'code_intent_keywords'
    _code_lang_with_action = re.compile(
        r'\b(?:typescript|javascript|java|golang|rust|python|c\+\+|c#|swift|kotlin|ruby|php)\b'
        r'.{0,60}'
        r'\b(?:yaz|oluştur|write|create|build|implement|function|class|api|code|script|program|uygula)\b',
        re.I,
    )
    if _code_lang_with_action.search(t):
        return 'code', 'code_language_with_action'

    # Late image intent: only if NOT a memory/context question (double safety)
    if not _is_memory_or_context_question(t):
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

        # TR/RU: kısa görsel komutları — yalnızca belirgin üretim niyeti varsa
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


_EXPLAIN_WITH_IMAGE = re.compile(
    r'\b(açıkla|açıklama|neden|niçin|explain|describe\s+how|instructions?|'
    r've\s+yaz|and\s+explain|and\s+describe|why\s+does)\b',
    re.I,
)


def wants_text_with_image_explanation(message_text: str) -> bool:
    """User explicitly wants prose together with the image."""
    return bool(_EXPLAIN_WITH_IMAGE.search(message_text or ''))


def is_pure_image_draw_turn(
    message_text: str,
    attachments: set[str],
    input_mode: str | None,
) -> bool:
    """
    True when this turn should only run image generation (no web/RAG/text follow-up).
    """
    try:
        from open_webui.utils.mws_gpt.image_grounding import wants_research_grounded_image_prompt

        if wants_research_grounded_image_prompt(message_text or ''):
            return False
    except Exception:
        pass
    mod, _ = classify_task_modality(
        message_text=message_text or '',
        attachments=attachments,
        input_mode=input_mode,
    )
    if mod != 'image_generation':
        return False
    if wants_text_with_image_explanation(message_text or ''):
        return False
    return True
