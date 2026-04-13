"""
High-fidelity multilingual image prompt construction for MWS image generation.

- Preserves user intent, named entities, actions, and spatial relations across TR/RU/EN/AR (script).
- Builds natural English prompts in a structured way (subject → action → relations → scene → composition → light → style → quality).
- Variation requests reuse the prior user subject with explicit diversity (angle, light, framing).
- Optional URL-injected page text (from url_page_context) is trimmed and used as visual grounding only.
"""

from __future__ import annotations

import hashlib
import random
import re

from open_webui.utils.mws_gpt.registry import _normalize_tr_keyboard_typos

# --- Quality & strict literal fidelity (avoid invented props / crowds / vehicles) ---
_REALISM_CORE = (
    'photorealistic rendering, highly detailed textures, sharp focus, coherent materials, natural colors'
)

# In-prompt repetition: models that ignore negative_prompt still see this.
_STRICT_LITERAL_FIDELITY = (
    'STRICT CONTENT RULES: Depict ONLY what the user explicitly asked for. '
    'Do NOT add any person, animal, vehicle, prop, text, building, accessory, background object, symbol, '
    'or environmental element unless explicitly requested or strictly required by the source image. '
    'Do NOT add extra people, crowds, animals, vehicles (cars, motorcycles, bicycles, equine animals), '
    'handheld props, signage text, flags, furniture, or unrelated background storytelling. '
    'If the user asked for one main subject (one building, one object, one animal), show exactly that count—no second figure or random foreground object. '
    'Unless the user specified a busy setting, use a minimal neutral background (clear sky, soft gradient, plain ground, or simple studio). '
    'No visible text, lettering, banners, captions, or watermarks in the image.'
)

_NEGATIVE_HALLUCINATION = (
    'Do not substitute different landmarks or subjects. Do not enrich the scene with unrelated creative filler.'
)

_DEFAULT_NEGATIVE = (
    'extra people, crowd, pedestrians, faces in background, duplicate subjects, '
    'motorcycle, bicycle, car, truck, bus, horse, random animals, birds, '
    'unrelated foreground objects, accessories, symbols, flags, street vendors, umbrellas, luggage, shopping bags, '
    'text overlay, watermark, logo, banner, subtitle, signage, random lettering, '
    'malformed anatomy, extra limbs, bad hands, fused fingers, blurry, low detail, jpeg artifacts, '
    'deformed perspective, cinematic clutter, random props, unsolicited secondary subjects'
)


def get_default_image_negative_prompt() -> str:
    """Strong default negative for backends that support it (disable with MWS_IMAGE_NEGATIVE_PROMPT=false)."""
    return _DEFAULT_NEGATIVE


def _format_structured_prompt(
    *,
    subject: str,
    action_pose: str = '',
    relations: str = '',
    environment: str = '',
    composition: str = '',
    lighting: str = '',
    style_extra: str = '',
    quality_extra: str = '',
) -> str:
    """Single coherent English paragraph for diffusion (not keyword soup)."""
    parts: list[str] = [
        f'Photorealistic image. Main subject: {subject.strip()}.',
    ]
    if action_pose.strip():
        parts.append(f'Action and pose: {action_pose.strip()}.')
    if relations.strip():
        parts.append(f'Spatial relationships and interactions: {relations.strip()}.')
    if environment.strip():
        parts.append(f'Setting and background: {environment.strip()}.')
    if composition.strip():
        parts.append(f'Composition and framing: {composition.strip()}.')
    if lighting.strip():
        parts.append(f'Lighting: {lighting.strip()}.')
    style_line = style_extra.strip() or (
        'Literal documentary style; high technical quality without inventing scene elements or cinematic filler.'
    )
    parts.append(f'Style target: {style_line}')
    qual = quality_extra.strip() or (
        'Ultra-detailed, crisp edges, realistic depth, high resolution; no invented set dressing.'
    )
    parts.append(f'Quality target: {qual}.')
    parts.append(_REALISM_CORE + '. ' + _STRICT_LITERAL_FIDELITY + ' ' + _NEGATIVE_HALLUCINATION)
    return ' '.join(parts)


# --- Known public figure normalizations (typos / keyboard) ---
_NAME_FIXES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r'\bmack\s*zakerburg\w*|\bmack\s*zuckerberg\b', re.I), 'Mark Zuckerberg'),
    (re.compile(r'\belon\s*musk\b', re.I), 'Elon Musk'),
    (re.compile(r'\bdonald\s*trump\b|\btrump\b', re.I), 'Donald Trump'),
)

# Phrase-level TR → EN (longest first)
_PHRASE_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r'\bkırmızı\s+spor\s+araba\b', re.I), 'red sports car'),
    (re.compile(r'\bmavi\s+bir\s+kedi\b', re.I), 'a blue cat'),
    (re.compile(r'\bmavi\s+kedi\b', re.I), 'blue cat'),
    (re.compile(r'\bspor\s+araba\b', re.I), 'sports car'),
    (re.compile(r'\bkardan\s+adam\b', re.I), 'snowman'),
    (re.compile(r'\bkartopu\b', re.I), 'snowball'),
    (re.compile(r'\bkoşan\s+uçak\b', re.I), 'airplane_in_motion_runway'),
    (re.compile(r'\bkoşan\s+(?:bir\s+)?uçak\b', re.I), 'airplane_in_motion_runway'),
    (re.compile(r'\bkanatlı\s+kedi\b', re.I), 'winged cat with visible wings'),
    (re.compile(r'\bkanatlı\b', re.I), 'winged'),
)

_TOKEN_WORDS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r'(?<![\w])kırmızı(?![\w])', re.I), 'red'),
    (re.compile(r'(?<![\w])kirmizi(?![\w])', re.I), 'red'),
    (re.compile(r'(?<![\w])mavi(?![\w])', re.I), 'blue'),
    (re.compile(r'(?<![\w])bir(?![\w])', re.I), 'a'),
    (re.compile(r'(?<![\w])kedi(?![\w])', re.I), 'cat'),
    (re.compile(r'(?<![\w])köpek(?![\w])', re.I), 'dog'),
    (re.compile(r'(?<![\w])kopek(?![\w])', re.I), 'dog'),
    (re.compile(r'(?<![\w])araba(?![\w])', re.I), 'car'),
    (re.compile(r'(?<![\w])uçak(?![\w])', re.I), 'airplane'),
    (re.compile(r'(?<![\w])ucak(?![\w])', re.I), 'airplane'),
    (re.compile(r'(?<![\w])portre(?![\w])', re.I), 'portrait'),
)

# Whole-message match only: "farklı ..." at the start must NOT count (would steal prior prompt).
_VARIATION_ONLY = re.compile(
    r'^[\s,.;:!]*(?:'
    r'bir\s+tane\s+daha|bir\s+daha|tane\s+daha|'
    r'tekrar(?:\s+çiz)?|yeniden\s+çiz|varyasyon|'
    r'another\s+one|one\s+more|\bagain\b|\bvariation\b|\brepeat\b|'
    r'ещ[ёе]\s+раз|ещё\s+один|еще\s+один|повтори|'
    r'مرة\s+أخرى|كمان\s+واحد'
    r')[\s,.;:!]*$',
    re.I,
)

_URL_PAGE_SPLIT = re.compile(
    r'(?s)(### Page content from URL[^\n]*\n.*?)(?:\n\n---\s*\n\n\*\*User message:\*\*\s*\n\n)(.*)$'
)

_WEB_RESEARCH_GROUND_SPLIT = re.compile(
    r'(?s)(### Web research \(visual grounding\).*?)(?:\n\n---\s*\n\n\*\*User message:\*\*\s*\n\n)(.*)$'
)


def _apply_name_fixes(s: str) -> str:
    t = s
    for rx, rep in _NAME_FIXES:
        t = rx.sub(rep, t)
    return t


def _strip_draw_wrappers(s: str) -> str:
    low = s.strip()
    low = re.sub(
        r'^(bana|lütfen|please|can you|could you|would you|draw me|make me|create|generate|нарисуй|создай|ارسم)\s+',
        '',
        low,
        flags=re.I,
    )
    low = re.sub(
        r'\s+(çiz|çizer\s*misin|ciz|draw|paint|make|generate|oluştur|üret|yap|resmi|изобрази)\s*\.?\s*$',
        '',
        low,
        flags=re.I,
    )
    return low.strip(' .,;:')


def split_url_injected_grounding(user_text: str) -> tuple[str | None, str]:
    """
    If url_page_context injected '### Page content from URL', split factual block vs real user ask.
    Same delimiter pattern for web research summaries (see image_grounding.inject_web_research_text_into_last_user_message).
    """
    t = user_text or ''
    m = _URL_PAGE_SPLIT.search(t)
    if not m:
        m = _WEB_RESEARCH_GROUND_SPLIT.search(t)
    if not m:
        return None, t.strip()
    grounding = m.group(1).strip()
    core = (m.group(2) or '').strip()
    if len(grounding) > 2000:
        grounding = grounding[:2000].rsplit('\n', 1)[0] + '\n[reference trimmed]'
    return grounding, (core or t.strip())


def is_variation_only_message(text: str) -> bool:
    t = _strip_draw_wrappers(_normalize_tr_keyboard_typos((text or '').strip()))
    if not t:
        return False
    if _VARIATION_ONLY.match(t.strip()):
        return True
    # "bir daha çiz" / "bir tane daha" with trailing words stripped already; allow ultra-short commands
    if re.match(
        r'^[\s,.;:!]*(?:bir\s+)?(?:tane\s+)?daha(?:\s+çiz)?[\s,.;:!]*$',
        t,
        re.I,
    ):
        return True
    if len(t) <= 18 and re.match(r'^[\s,.;:!]*(tekrar|again|repeat)[\s,.;:!]*$', t, re.I):
        return True
    return False


def get_prior_user_request_for_variation(messages: list[dict] | None, current_text: str) -> str | None:
    if not messages or not is_variation_only_message(current_text):
        return None
    from open_webui.utils.mws_gpt.registry import extract_last_user_text

    user_texts: list[str] = []
    for m in messages:
        if m.get('role') != 'user':
            continue
        u = extract_last_user_text([m])
        if u and u.strip():
            user_texts.append(u.strip())
    if len(user_texts) < 2:
        return None
    prev = user_texts[-2]
    _, prev_core = split_url_injected_grounding(prev)
    if is_variation_only_message(prev_core):
        return None
    return prev_core


def _stable_seed_from_text(*parts: str) -> int:
    h = hashlib.sha256('||'.join(p for p in parts if p).encode('utf-8')).hexdigest()
    return int(h[:8], 16)


def _variation_instruction(seed: int) -> str:
    rng = random.Random(seed)
    angle = rng.choice(
        [
            'a clearly different camera angle and focal length',
            'alternate framing with distinct negative space and subject placement',
            'a new three-quarter or profile viewpoint versus the prior shot',
            'a tighter or wider crop on the same subject only (no new objects)',
        ]
    )
    light = rng.choice(
        [
            'soft natural daylight with gentle shadows',
            'clean studio key light with subtle rim',
            'overcast even illumination',
            'warm golden-hour side light',
            'cool daylight with crisp contrast',
        ]
    )
    scene = rng.choice(
        [
            'same subject matter only; background stays minimal unless the user previously specified a place',
            'adjusted depth of field; no added props or characters',
            'subtle time-of-day shift without inventing new scene elements',
        ]
    )
    return (
        f'Variation request: produce a NEW image (not a near-duplicate). Change {angle}; lighting: {light}; '
        f'{scene}. Keep the same main subject, action, and relationships — vary only presentation. '
        f'Do not introduce new people, vehicles, animals, or objects.'
    )


def _composition_hint_from_text(t: str) -> str:
    low = (t or '').lower()
    if re.search(r'\b(portrait|vertical|dikey|portre|вертикальн|портретн)\b', low):
        return 'vertical portrait orientation, subject-centered, headroom balanced'
    if re.search(r'\b(landscape|horizontal|yatay|panoram|горизонтальн|широкий\s+кадр)\b', low):
        return 'horizontal wide composition; only the user-described elements in frame, minimal background'
    if re.search(r'\b(square|kare|квадрат)\b', low):
        return 'square balanced composition'
    return ''


def _try_holding_multilingual(core: str) -> str | None:
    """TR elinde / RU в руке / EN holding / AR يحمل في يده — person + object."""
    t = core.strip()

    # Turkish: "elinde köpek varken trump" (köpek while / with dog — Trump)
    m0 = re.search(
        r'elinde\s+(.+?)\s+varken\s+(.+)$',
        t,
        re.I | re.S,
    )
    if m0:
        obj_raw = m0.group(1).strip()
        who_raw = m0.group(2).strip()
        who = _apply_name_fixes(who_raw)
        ol = obj_raw.lower()
        if re.search(r'köpek|kopek|dog', ol):
            obj_en = 'a dog'
        elif re.search(r'kedi|cat', ol):
            obj_en = 'a cat'
        else:
            obj_en = _translate_residual_tr(obj_raw)
        return _format_structured_prompt(
            subject=f'{who} with {obj_en}',
            action_pose=f'only {who} and {obj_en} together as requested; correct contact if hands are implied',
            relations='no third person, no extra animals, no vehicles or props besides these subjects',
            environment='minimal neutral backdrop unless the user named a specific place',
            composition='medium shot on these two subjects only',
            lighting='soft natural light',
        )

    m = re.search(
        r'elinde\s+(.+?)\s+olan\s+(.+)$',
        t,
        re.I | re.S,
    )
    if m:
        obj_raw = m.group(1).strip()
        who_raw = m.group(2).strip()
        who = _apply_name_fixes(who_raw)
        ol = obj_raw.lower()
        if re.search(r'kartopu|snowball', ol):
            obj_en = 'a compact snowball'
        elif re.search(r'\bmuz\b|banana', ol):
            obj_en = 'a banana'
        elif re.search(r'kedi|cat', ol):
            obj_en = 'a cat'
        elif re.search(r'köpek|kopek|dog', ol):
            obj_en = 'a dog'
        else:
            obj_en = _translate_residual_tr(obj_raw)
            if not obj_en.lower().startswith(('a ', 'an ', 'the ')):
                obj_en = f'{obj_en}'
        return _format_structured_prompt(
            subject=who,
            action_pose=f'{who} clearly holding {obj_en} with correct hand-object contact',
            relations='hands and object anatomically correct; no third person or unrelated props',
            environment='minimal studio or plain backdrop unless the user specified a location',
            composition='medium shot on the interaction only',
            lighting='natural soft light on face and hands',
        )

    m = re.search(
        r'(?:в\s+руке|в\s+руках)\s*[:\-]?\s*(.+?)(?:\s+у\s+|\s+у\s+)(.+)$',
        t,
        re.I | re.S,
    )
    if m:
        obj = m.group(1).strip()
        who = _apply_name_fixes(m.group(2).strip())
        return _format_structured_prompt(
            subject=who,
            action_pose=f'{who} holds {obj} in hand, clear contact',
            relations='object scale believable relative to hands',
            composition='medium close-up',
            lighting='soft daylight',
        )

    m = re.search(
        r'(.+?)\s+(?:holding|holds)\s+(.+)$',
        t,
        re.I | re.S,
    )
    if m and len(t) < 220:
        who = _apply_name_fixes(m.group(1).strip().rstrip(','))
        obj = m.group(2).strip()
        return _format_structured_prompt(
            subject=who,
            action_pose=f'{who} holds {obj}',
            relations='accurate hand-object interaction',
            composition='medium shot',
            lighting='natural light',
        )
    return None


def _try_horseback_multilingual(core: str) -> str | None:
    t = core.strip()
    low = t.lower()

    m = re.search(
        r'(.+?)\s+\b(atın|atin)\s+üzerinde(?:ki)?\s+(?:giden|binen|oturan)\b',
        t,
        re.I | re.S,
    )
    if m:
        who = _apply_name_fixes(m.group(1).strip().rstrip(','))
        return _format_structured_prompt(
            subject=f'{who} on horseback',
            action_pose='riding pose with saddle; horse fully visible',
            relations='rider and horse connected; land-based scene',
            environment='outdoor ground or path; not on water',
            composition='full subject in frame',
            lighting='natural outdoor light',
            style_extra='equestrian scene; not maritime',
        )

    m2 = re.search(
        r'\b(atın|atin)\s+üzerinde(?:ki)?\s+(?:giden|binen|oturan)\s+(.+)$',
        t,
        re.I | re.S,
    )
    if m2:
        who = _apply_name_fixes(m2.group(2).strip())
        return _format_structured_prompt(
            subject=f'{who} riding a horse',
            action_pose='clear equestrian posture',
            relations='horse and rider both visible',
            environment='land; no boat deck or pier as primary ground',
            composition='wide enough to show horse legs',
            lighting='daylight',
        )

    # Turkish "at" = horse (word boundary avoids English "at" preposition and "katın" substring false matches)
    m3 = re.search(
        r'(.+?)\s+\bat\b\s+üzerinde(?:ki)?\s+(?:giden|binen|oturan)\b',
        t,
        re.I | re.S,
    )
    if m3:
        who = _apply_name_fixes(m3.group(1).strip().rstrip(','))
        return _format_structured_prompt(
            subject=f'{who} on horseback',
            action_pose='riding pose with saddle; horse fully visible',
            relations='rider and horse connected; land-based scene',
            environment='outdoor ground or path; not on water',
            composition='full subject in frame',
            lighting='natural outdoor light',
            style_extra='equestrian scene; not maritime',
        )

    m4 = re.search(
        r'\bat\b\s+üzerinde(?:ki)?\s+(?:giden|binen|oturan)\s+(.+)$',
        t,
        re.I | re.S,
    )
    if m4:
        who = _apply_name_fixes(m4.group(1).strip())
        return _format_structured_prompt(
            subject=f'{who} riding a horse',
            action_pose='clear equestrian posture',
            relations='horse and rider both visible',
            environment='land; no boat deck or pier as primary ground',
            composition='wide enough to show horse legs',
            lighting='daylight',
        )

    if re.search(
        r'riding\s+(?:a\s+)?horse|on\s+(?:a\s+)?horseback|верхом\s+на\s+лошади|на\s+лошади',
        t,
        re.I,
    ):
        who = _apply_name_fixes(t)
        return _format_structured_prompt(
            subject=who,
            action_pose='horseback riding, correct tack',
            relations='no substitution with boats, cars, or unrelated vehicles',
            environment='natural outdoor setting',
            composition='dynamic but readable',
            lighting='natural',
        )

    if 'trump' in low or 'donald' in low:
        if re.search(
            r'\bat\b\s*(üzerinde|uzerinde|üstünde|ustunde)|\bbinek\b|horseback|riding\s+a\s+horse',
            t,
            re.I,
        ):
            return _format_structured_prompt(
                subject='Donald Trump riding a horse',
                action_pose='clear riding posture on land',
                relations='horse must be a horse, not a boat or vehicle',
                environment='terrestrial outdoor scene',
                composition='full rider and horse',
                lighting='daylight',
            )
    return None


def _try_airplane_motion(core: str) -> str | None:
    if re.search(r'airplane_in_motion_runway', core, re.I):
        return _format_structured_prompt(
            subject='a jet aircraft',
            action_pose='takeoff roll, landing roll, or aggressive taxi; strong sense of motion',
            relations='aircraft is the dominant subject; no running human as main focus',
            environment='runway or sky appropriate to motion',
            composition='dynamic diagonal or side tracking feel',
            lighting='realistic outdoor or airport lighting',
        )
    low = core.lower()
    if re.search(r'koşan\s+(?:bir\s+)?uçak|koşan\s+ucak', low):
        return _format_structured_prompt(
            subject='a jet aircraft',
            action_pose='high-speed motion on runway or low pass',
            relations='no accidental emphasis on a running person',
            environment='airfield context',
            composition='aircraft fills the frame',
            lighting='clear visibility',
        )
    return None


def _try_snowball_only(core: str) -> str | None:
    low = core.lower()
    if re.search(r'\bkartopu\b|\bsnowball\b', low) and 'banana' not in low:
        if not re.search(r'\b(trump|biden|person|adam|kişi|holding|elinde|portre)\b', low, re.I):
            return _format_structured_prompt(
                subject='a single compact snowball only',
                action_pose='snowball alone on a plain surface; no people, hands, faces, or figures',
                relations='only this object; no secondary subjects',
                environment='plain neutral seamless backdrop; no props',
                composition='centered product-style or macro framing',
                lighting='soft even lighting',
            )
    return None


def _try_architecture_only(core: str) -> str | None:
    """Building / campus / landmark requests without people or narrative action in the text."""
    if re.search(
        r'\b(elinde|varken|holding|binen|oturan|giden\s+trump|portre|köpek|kardan\s+adam|uçan|kanatlı|'
        r'\bat\b\s*üzerinde|horseback|riding)\b',
        core,
        re.I,
    ):
        return None
    if re.search(r'\b(öğrenci|student|kalabalık|crowd|insanlar|yürüyen|walking)\b', core, re.I):
        return None
    if re.search(
        r'\b(trump|musk|biden|putin|obama|erdogan|zelensky|portre|kişi|adam|kadın|çocuk)\b',
        core,
        re.I,
    ):
        return None
    if not re.search(
        r'\b(üniversit|universit|üniversite|federal|ural|kampüs|campus|mimari|bina|building|'
        r'cathedral|mosque|kilise|landmark|facade)\w*',
        core,
        re.I,
    ):
        return None
    en = _strip_draw_wrappers(_translate_residual_tr(core))
    if len(en) < 2:
        en = core
    return _format_structured_prompt(
        subject=f'architectural exterior or campus as described only: {en}',
        action_pose='static architecture; no people, animals, or vehicles in the frame',
        relations='no pedestrians, motorcycles, bicycles, equines, or staged foreground characters',
        environment='minimal setting for scale only: sky, paving, lawn, or simple plaza—no busy street life',
        composition='architectural documentary view, straight verticals',
        lighting='neutral clear daylight',
        style_extra='literal building visualization',
    )


def _try_literal_scene_keywords(core: str) -> str | None:
    """Rain + tram etc.: keep scene tight to named elements."""
    low = core.lower()
    if not re.search(r'\b(tramvay|tram|trolley)\b', low):
        return None
    en = _strip_draw_wrappers(_translate_residual_tr(core))
    if len(en) < 2:
        en = core
    rain = bool(re.search(r'yağmur|rain|дождь', low))
    env = 'rainy atmosphere as stated' if rain else 'atmosphere only as stated'
    return _format_structured_prompt(
        subject=f'scene exactly as described: {en}',
        action_pose='only the named elements (e.g. tram and weather); no extra characters or vehicles',
        relations='no crowds, vendors, unrelated cars, or animals unless explicitly named',
        environment=f'{env}; minimal city context—no invented background story',
        composition='wide shot limited to described elements',
        lighting='matching weather; no dramatic unrelated elements',
        style_extra='literal scene, not a crowded movie set',
    )


def _translate_residual_tr(fragment: str) -> str:
    t = fragment
    for rx, rep in _PHRASE_REPLACEMENTS:
        t = rx.sub(rep, t)
    for rx, rep in _TOKEN_WORDS:
        t = rx.sub(rep, t)
    return t.strip()


def _looks_non_latin_or_mixed(s: str) -> bool:
    if re.search(r'[ğüşıöçĞÜŞİÖÇİ]', s):
        return True
    if re.search(r'[А-Яа-яЁё]', s):
        return True
    if re.search(r'[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿]', s):
        return True
    return bool(
        re.search(
            r'\b(bana|çiz|olan|üzerinde|giden|binen|bir|şey|için|veya|ile|в|на|с|для|или)\b',
            s,
            re.I,
        )
    )


def _compose_from_glossary(core: str) -> str:
    t = core.strip()
    for rx, rep in _PHRASE_REPLACEMENTS:
        t = rx.sub(rep, t)
    if 'airplane_in_motion_runway' in t.lower():
        r = _try_airplane_motion('airplane_in_motion_runway')
        if r:
            return r
    for rx, rep in _TOKEN_WORDS:
        t = rx.sub(rep, t)
    en = _strip_draw_wrappers(t)
    if len(en) < 2:
        en = core
    comp = _composition_hint_from_text(core)
    return _format_structured_prompt(
        subject=f'literal depiction of: {en}',
        action_pose='exactly as described; no invented substitutes or extra characters',
        relations='preserve spatial language only; do not add unmentioned companions or props',
        environment='only if implied or stated; otherwise plain minimal ground and sky',
        composition=comp or 'single clear focal subject; minimal background',
        lighting='soft even light unless the user specified otherwise',
    )


def _build_base_image_prompt(working_core: str) -> str:
    core = working_core.strip()
    if not core:
        return _format_structured_prompt(subject='a high-quality detailed photographic scene')

    scene = _try_holding_multilingual(core)
    if scene:
        return scene

    hb = _try_horseback_multilingual(core)
    if hb:
        return hb

    am = _try_airplane_motion(core)
    if am:
        return am

    sb = _try_snowball_only(core)
    if sb:
        return sb

    arch = _try_architecture_only(core)
    if arch:
        return arch

    scene_tram = _try_literal_scene_keywords(core)
    if scene_tram:
        return scene_tram

    if _looks_non_latin_or_mixed(core):
        return _compose_from_glossary(core)

    comp = _composition_hint_from_text(core)
    return _format_structured_prompt(
        subject=f'faithful rendering of: {core}',
        action_pose='exactly as requested; no added figures or props',
        relations='only entities the user named',
        environment='as stated; otherwise minimal neutral setting—no invented environment story',
        composition=comp or 'clear single-subject framing; minimal background',
        lighting='appropriate to the described scene',
    )


def _append_grounding_block(base: str, grounding: str | None) -> str:
    if not grounding or not grounding.strip():
        return base
    g = grounding.strip()
    return (
        f'{base} '
        f'Visual reference (match architecture, materials, and layout; do not render page text as an overlay): {g}'
    )


def build_mws_image_prompt(user_text: str, previous_user_text: str | None = None) -> str:
    """
    Build an English-leaning prompt for OpenAI-compatible image APIs.
    """
    raw = (user_text or '').strip()
    if not raw:
        return _format_structured_prompt(subject='a detailed photographic scene')

    grounding, core_raw = split_url_injected_grounding(_normalize_tr_keyboard_typos(raw))
    core_raw = _apply_name_fixes(core_raw)
    t = _normalize_tr_keyboard_typos(core_raw)
    core = _strip_draw_wrappers(t)

    variation = is_variation_only_message(_normalize_tr_keyboard_typos(raw))
    if variation and previous_user_text:
        working = _strip_draw_wrappers(_normalize_tr_keyboard_typos(previous_user_text.strip()))
    else:
        working = core

    if variation and not previous_user_text and is_variation_only_message(working):
        seed = _stable_seed_from_text(raw, 'variation_orphan') ^ random.randrange(1 << 29)
        base = _format_structured_prompt(
            subject='the same concept as the previous request',
            action_pose='new interpretation',
            composition='clearly distinct from the prior image',
            lighting='varied',
            quality_extra='high detail',
        )
        return _append_grounding_block(f'{base} {_variation_instruction(seed)}', grounding)

    base = _build_base_image_prompt(working)

    if variation:
        seed = _stable_seed_from_text(working, raw) ^ random.randrange(1 << 29)
        base = f'{base} {_variation_instruction(seed)}'

    return _append_grounding_block(base, grounding)


def get_default_image_edit_negative_prompt() -> str:
    """Tight negative hints for identity-preserving edits (embedded in edit prompt when API has no separate field)."""
    return (
        'different person, identity swap, replacement face, lookalike, twin stranger, '
        'extra people, crowd, duplicate faces, '
        'extra limbs, deformed hands, fused fingers, plastic skin, wax figure, '
        'random unrelated props, staged clutter, '
        'subtitles, watermark, logo, banner text, '
        'low resolution, heavy blur, jpeg artifacts, oversharpen halos'
    )


def build_mws_image_edit_prompt(user_instruction: str) -> str:
    """
    English structured prompt for image-to-image / reference edits (not t2i generation).
    Preserves subject identity; user text may be TR/RU/EN/AR/mixed.
    """
    ui = (user_instruction or '').strip()
    if not ui:
        ui = 'Apply subtle quality improvements only; keep everything else unchanged.'
    neg = get_default_image_edit_negative_prompt()
    return (
        'IMAGE-TO-IMAGE EDIT — reference-driven. Use the uploaded photograph as the only source image. '
        'Preserve the same real person: keep facial identity, approximate age, skin tone, and hair '
        'unless the user explicitly asked to change them. '
        'Preserve overall pose, body proportions, and camera framing unless the instruction requires changing them. '
        'Apply only the modifications described in the user request. '
        'Do not invent a new subject or a different person. '
        'Do not add extra people, animals, vehicles, or unrelated foreground objects unless requested. '
        'Keep lighting and shadows coherent with the scene. '
        'Photorealistic output, high detail, natural materials.\n\n'
        f'User request (any language; interpret intent faithfully): {ui}\n\n'
        f'Avoid: {neg}.'
    )
