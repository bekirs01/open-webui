"""Acceptance-style tests for MWS Auto routing (no network)."""

from types import SimpleNamespace

from open_webui.utils.mws_gpt.router import _pick_fallback, decide_mws_model
from open_webui.utils.mws_gpt.registry import collect_attachment_kinds
from open_webui.utils.mws_gpt.orchestrator import AUTO_TEXT_SIMPLE_ORDER
from open_webui.utils.mws_gpt.team_registry import TEAM_ALLOWLIST, get_primary_capability


def _config(**kwargs):
    base = dict(
        MWS_GPT_AUTO_ROUTING=True,
        MWS_GPT_ORCHESTRATION=True,
        ENABLE_IMAGE_EDIT=False,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _openai_models() -> dict:
    return {mid: {'id': mid} for mid in TEAM_ALLOWLIST}


def test_plain_text_chat_not_image_gen():
    d = decide_mws_model(
        manual_model_id='auto',
        message_text='Merhaba, bugün nasılsın?',
        attachments=set(),
        input_mode=None,
        openai_models=_openai_models(),
        config=_config(),
        params={},
    )
    assert d['modality'] == 'text'
    assert d['routing_decision']['detailed_task'] == 'text_chat'
    assert d['model_id'] == AUTO_TEXT_SIMPLE_ORDER[0]
    assert d['routing_decision']['selected_model'] != 'qwen-image'


def test_hard_reasoning_uses_reasoning_tier():
    d = decide_mws_model(
        manual_model_id='mws:auto',
        message_text='Bu algoritmanın zaman karmaşıklığını adım adım analiz et',
        attachments=set(),
        input_mode=None,
        openai_models=_openai_models(),
        config=_config(),
        params={},
    )
    assert d['complexity'] == 'hard'
    assert d['routing_decision']['detailed_task'] == 'reasoning'
    assert d['model_id'] in (
        'Qwen3-235B-A22B-Instruct-2507-FP8',
        'glm-4.6-357b',
        'deepseek-r1-distill-qwen-32b',
        'QwQ-32B',
        'kimi-k2-instruct',
    )


def test_code_request_prefers_team_coder():
    d = decide_mws_model(
        manual_model_id='auto',
        message_text='Bu Python kodunu düzelt: def foo(): return 1/0',
        attachments=set(),
        input_mode=None,
        openai_models=_openai_models(),
        config=_config(),
        params={},
    )
    assert d['modality'] == 'code'
    assert d['routing_decision']['detailed_task'] in ('code_generation', 'code_explanation')
    assert d['model_id'] == 'qwen3-coder-480b-a35b'


def test_explicit_image_generation():
    d = decide_mws_model(
        manual_model_id='auto',
        message_text='Bana kırmızı bir araba çiz',
        attachments=set(),
        input_mode=None,
        openai_models=_openai_models(),
        config=_config(),
        params={},
    )
    assert d['modality'] == 'image_generation'
    assert d['routing_decision']['detailed_task'] == 'image_generation'
    assert d['model_id'] == 'qwen-image'


def test_vision_with_image_attachment():
    d = decide_mws_model(
        manual_model_id='auto',
        message_text='Bunu açıkla',
        attachments={'image'},
        input_mode=None,
        openai_models=_openai_models(),
        config=_config(),
        params={},
    )
    assert d['modality'] == 'vision'
    assert d['routing_decision']['detailed_task'] == 'image_understanding'
    assert d['model_id'] == 'qwen2.5-vl-72b'


def test_audio_attachment_marks_stt_and_text_completion_model():
    d = decide_mws_model(
        manual_model_id='auto',
        message_text='Bunu yazıya dök',
        attachments={'audio'},
        input_mode=None,
        openai_models=_openai_models(),
        config=_config(),
        params={},
    )
    assert d['modality'] == 'text'
    assert d['routing_decision']['detailed_task'] == 'audio_transcription'
    assert 'stt_pipeline' in d['routing_decision']['requires_tools']
    assert get_primary_capability(d['model_id']) == 'text'


def test_pdf_summarization_document_attachment():
    files = [{'content_type': 'application/pdf', 'type': 'file'}]
    att = collect_attachment_kinds(files, None)
    assert 'document' in att
    d = decide_mws_model(
        manual_model_id='auto',
        message_text='Özetle',
        attachments=att,
        input_mode=None,
        openai_models=_openai_models(),
        config=_config(),
        params={},
    )
    assert d['modality'] == 'text'
    assert d['routing_decision']['detailed_task'] == 'summarization'
    assert 'file_extraction_pipeline' in d['routing_decision']['requires_tools']


def test_memory_question_not_image_generation():
    d = decide_mws_model(
        manual_model_id='auto',
        message_text='Benim adım ne ve demin ne resmi çizdin?',
        attachments=set(),
        input_mode=None,
        openai_models=_openai_models(),
        config=_config(),
        params={},
    )
    assert d['modality'] == 'text'
    assert d['routing_decision']['detailed_task'] == 'memory_lookup'
    assert d['model_id'] != 'qwen-image'


def test_conversion_export_route_not_plain_chat():
    d = decide_mws_model(
        manual_model_id='auto',
        message_text='Bana bunu JPG olarak ver',
        attachments={'image'},
        input_mode=None,
        openai_models=_openai_models(),
        config=_config(),
        params={},
    )
    assert d['modality'] == 'export'
    assert d['routing_decision']['detailed_task'] == 'extraction'
    assert 'export_or_conversion_pipeline' in d['routing_decision']['requires_tools']


def test_embedding_never_auto_chat_pick():
    models = _openai_models()
    assert 'bge-m3' in models
    d = decide_mws_model(
        manual_model_id='auto',
        message_text='Genel bir soru: nedir yapay zeka?',
        attachments=set(),
        input_mode=None,
        openai_models=models,
        config=_config(),
        params={},
    )
    assert get_primary_capability(d['model_id']) != 'embedding'


def test_image_family_fallback_chain():
    av = {'qwen-image', 'qwen-image-lightning'}
    fb = _pick_fallback('image_generation', 'qwen-image', av)
    assert fb == 'qwen-image-lightning'


# ============================================================================
# PER-TURN ROUTING: model switches automatically when task changes
# ============================================================================

def test_per_turn_greeting_then_code():
    """Turn 1: simple greeting → strong text; Turn 2: code fix → code model."""
    models = _openai_models()
    cfg = _config()

    d1 = decide_mws_model(
        manual_model_id='auto',
        message_text='merhaba',
        attachments=set(),
        input_mode=None,
        openai_models=models,
        config=cfg,
        params={},
    )
    assert d1['modality'] == 'text'
    assert get_primary_capability(d1['model_id']) == 'text'
    assert d1['model_id'] != 'qwen-image'

    d2 = decide_mws_model(
        manual_model_id='auto',
        message_text='bu python kodunu düzelt: def foo(): return 1/0',
        attachments=set(),
        input_mode=None,
        openai_models=models,
        config=cfg,
        params={},
    )
    assert d2['modality'] == 'code'
    assert d2['model_id'] == 'qwen3-coder-480b-a35b'
    assert d2['model_id'] != d1['model_id']


def test_per_turn_code_then_image():
    """Turn 1: code → code model; Turn 2: draw → image model."""
    models = _openai_models()
    cfg = _config()

    d1 = decide_mws_model(
        manual_model_id='auto',
        message_text='bu kodu düzelt: print("hello"',
        attachments=set(),
        input_mode=None,
        openai_models=models,
        config=cfg,
        params={},
    )
    assert d1['modality'] == 'code'

    d2 = decide_mws_model(
        manual_model_id='auto',
        message_text='bana mavi bir araba çiz',
        attachments=set(),
        input_mode=None,
        openai_models=models,
        config=cfg,
        params={},
    )
    assert d2['modality'] == 'image_generation'
    assert d2['model_id'] == 'qwen-image'


def test_per_turn_image_then_vision():
    """Turn 1: image gen; Turn 2: uploaded image analysis → vision model."""
    models = _openai_models()
    cfg = _config()

    d1 = decide_mws_model(
        manual_model_id='auto',
        message_text='kedi resmi çiz',
        attachments=set(),
        input_mode=None,
        openai_models=models,
        config=cfg,
        params={},
    )
    assert d1['modality'] == 'image_generation'

    d2 = decide_mws_model(
        manual_model_id='auto',
        message_text='bunu açıkla',
        attachments={'image'},
        input_mode=None,
        openai_models=models,
        config=cfg,
        params={},
    )
    assert d2['modality'] == 'vision'
    assert d2['model_id'] == 'qwen2.5-vl-72b'


# ============================================================================
# SIMPLE GREETING gets strong general text model
# ============================================================================

def test_simple_greeting_nasilsin():
    """'nasılsın' → strong general text model, not weak or image."""
    d = decide_mws_model(
        manual_model_id='auto',
        message_text='nasılsın',
        attachments=set(),
        input_mode=None,
        openai_models=_openai_models(),
        config=_config(),
        params={},
    )
    assert d['modality'] == 'text'
    strong_text = {'qwen2.5-72b-instruct', 'gpt-oss-120b', 'llama-3.3-70b-instruct', 'qwen3-32b'}
    assert d['model_id'] in strong_text, f"Expected strong text model, got {d['model_id']}"


def test_simple_currency_question():
    """'1 tl kaç ruble' → text, strong model, NOT image generation."""
    d = decide_mws_model(
        manual_model_id='auto',
        message_text='1 tl kaç ruble',
        attachments=set(),
        input_mode=None,
        openai_models=_openai_models(),
        config=_config(),
        params={},
    )
    assert d['modality'] == 'text'
    assert d['model_id'] != 'qwen-image'
    assert get_primary_capability(d['model_id']) == 'text'


# ============================================================================
# MEMORY QUESTION routes to text, never image
# ============================================================================

def test_memory_my_name():
    """'benim adım neydi' → text/memory, not image."""
    d = decide_mws_model(
        manual_model_id='auto',
        message_text='benim adım neydi',
        attachments=set(),
        input_mode=None,
        openai_models=_openai_models(),
        config=_config(),
        params={},
    )
    assert d['modality'] == 'text'
    assert d['model_id'] != 'qwen-image'
    assert d['routing_decision']['detailed_task'] == 'memory_lookup'


# ============================================================================
# AUDIO TRANSCRIPTION
# ============================================================================

def test_audio_transcription_routes_text_model():
    """[audio attached] → text model (STT runs in pipeline, chat uses text)."""
    d = decide_mws_model(
        manual_model_id='auto',
        message_text='bunu yazıya dök',
        attachments={'audio'},
        input_mode=None,
        openai_models=_openai_models(),
        config=_config(),
        params={},
    )
    assert d['modality'] == 'text'
    cap = get_primary_capability(d['model_id'])
    assert cap == 'text', f"Audio chat should use text model, got {d['model_id']} ({cap})"


# ============================================================================
# FALLBACK: primary model removed from available set
# ============================================================================

def test_fallback_when_primary_unavailable():
    """If qwen-image is not in /models, Auto must still pick the lightning variant."""
    models_no_primary = {mid: {'id': mid} for mid in TEAM_ALLOWLIST if mid != 'qwen-image'}
    d = decide_mws_model(
        manual_model_id='auto',
        message_text='bana kedi çiz',
        attachments=set(),
        input_mode=None,
        openai_models=models_no_primary,
        config=_config(),
        params={},
    )
    assert d['modality'] == 'image_generation'
    assert d['model_id'] == 'qwen-image-lightning'


def test_fallback_code_model_unavailable():
    """If qwen3-coder is not available, code routes to next best (reasoning/text)."""
    models_no_coder = {mid: {'id': mid} for mid in TEAM_ALLOWLIST if mid != 'qwen3-coder-480b-a35b'}
    d = decide_mws_model(
        manual_model_id='auto',
        message_text='bu kodu düzelt: def foo(): pass',
        attachments=set(),
        input_mode=None,
        openai_models=models_no_coder,
        config=_config(),
        params={},
    )
    assert d['modality'] == 'code'
    assert d['model_id'] != 'qwen3-coder-480b-a35b'
    cap = get_primary_capability(d['model_id'])
    assert cap == 'text', f"Code fallback should be text-capable, got {cap}"


def test_fallback_vision_model_unavailable():
    """If primary vision model is unavailable, next vision model is used."""
    models_no_vl72 = {mid: {'id': mid} for mid in TEAM_ALLOWLIST if mid != 'qwen2.5-vl-72b'}
    d = decide_mws_model(
        manual_model_id='auto',
        message_text='bunu açıkla',
        attachments={'image'},
        input_mode=None,
        openai_models=models_no_vl72,
        config=_config(),
        params={},
    )
    assert d['modality'] == 'vision'
    assert d['model_id'] in ('qwen3-vl-30b-a3b-instruct', 'qwen2.5-vl', 'cotype-pro-vl-32b')


# ============================================================================
# PROMPT CONTAMINATION REGRESSION — simple greeting should not be bizarre
# ============================================================================

def test_simple_greeting_not_image_or_code():
    """Regression: simple greeting must never route to image/code/embedding/audio."""
    for msg in ('merhaba', 'selam', 'hello', 'hi', 'günaydın', 'hey'):
        d = decide_mws_model(
            manual_model_id='auto',
            message_text=msg,
            attachments=set(),
            input_mode=None,
            openai_models=_openai_models(),
            config=_config(),
            params={},
        )
        assert d['modality'] == 'text', f"'{msg}' got modality={d['modality']}"
        cap = get_primary_capability(d['model_id'])
        assert cap == 'text', f"'{msg}' got model={d['model_id']} cap={cap}"


# ============================================================================
# MANUAL MODEL SELECTION still works
# ============================================================================

def test_manual_model_not_altered():
    """When user picks a specific model, Auto must NOT override it."""
    d = decide_mws_model(
        manual_model_id='deepseek-r1-distill-qwen-32b',
        message_text='merhaba',
        attachments=set(),
        input_mode=None,
        openai_models=_openai_models(),
        config=_config(),
        params={},
    )
    assert d['model_id'] == 'deepseek-r1-distill-qwen-32b'
    assert d['reason'] == 'manual_override'


# ============================================================================
# ROUTING DECISION contains debug info
# ============================================================================

def test_routing_decision_has_debug_fields():
    """Every Auto routing must include task, family, model, fallback, confidence."""
    d = decide_mws_model(
        manual_model_id='auto',
        message_text='merhaba nasılsın',
        attachments=set(),
        input_mode=None,
        openai_models=_openai_models(),
        config=_config(),
        params={},
    )
    rd = d['routing_decision']
    assert rd['primary_task'] in ('text', 'code', 'vision', 'image_generation', 'export')
    assert rd['detailed_task'] != ''
    assert rd['selected_model'] is not None
    assert rd['confidence'] > 0
    assert isinstance(rd['fallback_chain'], list)
