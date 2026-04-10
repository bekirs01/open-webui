"""Unit tests for MWS GPT team registry and Auto router (no network)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from open_webui.utils.mws_gpt.image_prompt import build_mws_image_prompt
from open_webui.utils.mws_gpt.registry import (
    classify_task_modality,
    extract_last_user_text,
    is_pure_image_draw_turn,
    should_inject_web_search_for_message,
)
from open_webui.utils.mws_gpt.router import LEGACY_AUTO_IDS, MWS_AUTO_ID, decide_mws_model, resolve_mws_chat_model
from open_webui.utils.mws_gpt.team_registry import (
    MODEL_PRIMARY_CAPABILITY,
    TEAM_ALLOWLIST,
    get_primary_capability,
    pick_auto_target_model,
)
from open_webui.utils.mws_gpt.auto_workflow import build_auto_workflow
from open_webui.utils.mws_gpt.orchestrator import estimate_complexity
from open_webui.utils.mws_gpt.export_intent import parse_export_intent, export_intent_blocks_web_search
import open_webui.utils.mws_gpt.active as active_mod


def test_auto_sentinel_is_not_upstream_id():
    assert MWS_AUTO_ID == 'auto'
    assert 'mws:auto' in LEGACY_AUTO_IDS
    assert 'auto' in LEGACY_AUTO_IDS


def test_team_models_have_primary_capability():
    assert MODEL_PRIMARY_CAPABILITY.get('qwen-image') == 'image_generation'
    assert MODEL_PRIMARY_CAPABILITY.get('bge-m3') == 'embedding'
    assert 'qwen-image-lightning' in TEAM_ALLOWLIST


def test_get_primary_capability_heuristic_namespaced_image():
    assert get_primary_capability('org/mws/qwen-image') == 'image_generation'
    assert get_primary_capability('foo-qwen-image-v2') == 'image_generation'


def test_get_primary_capability_heuristic_embedding_and_whisper():
    assert get_primary_capability('org/BAAI/bge-multilingual-gemma2') == 'embedding'
    assert get_primary_capability('custom/whisper-medium') == 'audio_transcription'


def test_auto_workflow_vision_then_text():
    cfg = SimpleNamespace(MWS_AUTO_MULTI_MODEL=True)
    av = {'qwen3-vl-30b-a3b-instruct', 'llama-3.3-70b-instruct'}
    wf = build_auto_workflow(
        decision={'modality': 'vision', 'model_id': 'qwen3-vl-30b-a3b-instruct'},
        available=av,
        config=cfg,
        message_text='bu görselde ne var',
        attachments={'image'},
    )
    assert wf['kind'] == 'vision_then_text'
    assert wf['vision_model_id'] == 'qwen3-vl-30b-a3b-instruct'
    assert wf['synthesizer_model_id'] == 'llama-3.3-70b-instruct'


def test_auto_workflow_single_when_multi_off():
    cfg = SimpleNamespace(MWS_AUTO_MULTI_MODEL=False)
    wf = build_auto_workflow(
        decision={'modality': 'vision', 'model_id': 'qwen3-vl-30b-a3b-instruct'},
        available={'qwen3-vl-30b-a3b-instruct', 'llama-3.3-70b-instruct'},
        config=cfg,
        message_text='x',
        attachments={'image'},
    )
    assert wf['kind'] == 'single'


def test_pure_image_no_web_inject():
    assert not should_inject_web_search_for_message(
        message_text='bana kartopu resmi çiz',
        attachments=set(),
        input_mode=None,
    )


def test_pure_image_prompt_snowball_not_banana():
    p = build_mws_image_prompt('bana kartopu resmi çiz')
    assert 'snowball' in p.lower()
    assert 'banana' not in p.lower()


def test_image_prompt_zuckerberg_banana():
    p = build_mws_image_prompt('bana elinde muz olan mack zakerburgu ciz')
    pl = p.lower()
    assert 'zuckerberg' in pl or 'mark' in pl
    assert 'banana' in pl


def test_is_pure_image_draw_turn():
    assert is_pure_image_draw_turn('kardan adam çiz', set(), None)
    assert not is_pure_image_draw_turn('bunu açıkla ve çiz', set(), None)


def test_estimate_complexity_hard_for_proof():
    c, r = estimate_complexity(
        message_text='Prove rigorously this multi-step theorem formal contradiction.',
        modality='text',
        attachments=set(),
    )
    assert c == 'hard'
    assert r == 'reasoning_keywords'


def test_decide_auto_hard_prefers_reasoning_chain():
    cfg = SimpleNamespace(MWS_GPT_AUTO_ROUTING=True, MWS_GPT_DEFAULT_TEXT_MODEL='', MWS_GPT_ORCHESTRATION=True)
    models = {
        'deepseek-r1-distill-qwen-32b': {'id': 'deepseek-r1-distill-qwen-32b', 'tags': [{'name': 'mws'}]},
        'llama-3.3-70b-instruct': {'id': 'llama-3.3-70b-instruct', 'tags': [{'name': 'mws'}]},
    }
    out = decide_mws_model(
        manual_model_id='auto',
        message_text='Prove rigorously this multi-step formal lemma.',
        attachments=set(),
        input_mode=None,
        openai_models=models,
        config=cfg,
    )
    assert out['model_id'] == 'deepseek-r1-distill-qwen-32b'
    assert out.get('complexity') == 'hard'


def test_pick_auto_image_prefers_qwen_image():
    av = {'qwen-image', 'qwen-image-lightning', 'llama-3.3-70b-instruct'}
    mid, _ = pick_auto_target_model('image_generation', av)
    assert mid == 'qwen-image'


def test_pick_auto_text_prefers_llama():
    av = {'llama-3.3-70b-instruct', 'qwen3-32b'}
    mid, _ = pick_auto_target_model('text', av)
    assert mid == 'llama-3.3-70b-instruct'


def test_decide_manual_override():
    cfg = SimpleNamespace(MWS_GPT_AUTO_ROUTING=True, MWS_GPT_DEFAULT_TEXT_MODEL='')
    out = decide_mws_model(
        manual_model_id='deepseek-r1-distill-qwen-32b',
        message_text='x',
        attachments=set(),
        input_mode=None,
        openai_models={'deepseek-r1-distill-qwen-32b': {'id': 'deepseek-r1-distill-qwen-32b'}},
        config=cfg,
    )
    assert out['model_id'] == 'deepseek-r1-distill-qwen-32b'
    assert out['reason'] == 'manual_override'


def test_decide_auto_resolves_to_real_model():
    cfg = SimpleNamespace(MWS_GPT_AUTO_ROUTING=True, MWS_GPT_DEFAULT_TEXT_MODEL='', MWS_GPT_ORCHESTRATION=True)
    models = {
        'llama-3.3-70b-instruct': {'id': 'llama-3.3-70b-instruct', 'tags': [{'name': 'mws'}]},
        'qwen-image': {'id': 'qwen-image', 'tags': [{'name': 'mws'}]},
    }
    out = decide_mws_model(
        manual_model_id='auto',
        message_text='hello world',
        attachments=set(),
        input_mode=None,
        openai_models=models,
        config=cfg,
    )
    assert out['model_id'] == 'llama-3.3-70b-instruct'
    assert out['model_id'] not in LEGACY_AUTO_IDS


def test_decide_auto_image_intent():
    cfg = SimpleNamespace(MWS_GPT_AUTO_ROUTING=True, MWS_GPT_DEFAULT_TEXT_MODEL='', MWS_GPT_ORCHESTRATION=True)
    models = {
        'qwen-image': {'id': 'qwen-image', 'tags': [{'name': 'mws'}]},
        'qwen-image-lightning': {'id': 'qwen-image-lightning', 'tags': [{'name': 'mws'}]},
    }
    out = decide_mws_model(
        manual_model_id='auto',
        message_text='draw a red car',
        attachments=set(),
        input_mode=None,
        openai_models=models,
        config=cfg,
    )
    assert out['model_id'] == 'qwen-image'


def test_classify_image_intent_multilingual():
    mod, _ = classify_task_modality(message_text='araba çiz', attachments=set(), input_mode=None)
    assert mod == 'image_generation'


def test_classify_image_turkish_phrases():
    for msg in ('bana resim çiz', 'logo tasarla', 'görsel oluştur', 'bir poster yap'):
        mod, _ = classify_task_modality(message_text=msg, attachments=set(), input_mode=None)
        assert mod == 'image_generation', msg


def test_classify_text_not_code_for_python_general():
    mod, _ = classify_task_modality(message_text='Python nedir?', attachments=set(), input_mode=None)
    assert mod == 'text'


def test_classify_image_before_code_when_both_words():
    mod, _ = classify_task_modality(
        message_text='python ile ilgili değil, sadece kedi resmi çiz',
        attachments=set(),
        input_mode=None,
    )
    assert mod == 'image_generation'


def test_extract_last_user_text_multipart():
    messages = [
        {'role': 'user', 'content': [{'type': 'text', 'text': 'Hi'}]},
    ]
    assert extract_last_user_text(messages) == 'Hi'


def test_logs_no_secret_leak():
    cfg = SimpleNamespace(
        MWS_GPT_AUTO_ROUTING=True,
        MWS_GPT_ORCHESTRATION=True,
        MWS_GPT_DEFAULT_TEXT_MODEL='',
    )
    models = {'llama-3.3-70b-instruct': {'id': 'llama-3.3-70b-instruct'}}
    out = decide_mws_model(
        manual_model_id='auto',
        message_text='x',
        attachments=set(),
        input_mode=None,
        openai_models=models,
        config=cfg,
    )
    dumped = str(out)
    assert 'sk-' not in dumped


def test_resolve_auto_never_returns_sentinel():
    prev = active_mod.is_mws_gpt_active
    active_mod.is_mws_gpt_active = lambda c: True
    try:
        request = MagicMock()
        request.app.state.config = SimpleNamespace(
            MWS_GPT_AUTO_ROUTING=True,
            MWS_GPT_ORCHESTRATION=True,
            MWS_GPT_DEFAULT_TEXT_MODEL='',
            MWS_GPT_TAG='mws',
        )
        request.app.state.OPENAI_MODELS = {
            'llama-3.3-70b-instruct': {'id': 'llama-3.3-70b-instruct', 'tags': [{'name': 'mws'}]},
        }
        rid, meta = resolve_mws_chat_model(
            request,
            {'model': 'auto', 'messages': [{'role': 'user', 'content': 'hello'}]},
        )
        assert rid == 'llama-3.3-70b-instruct'
        assert rid not in LEGACY_AUTO_IDS
        assert meta['resolved_model_id'] == rid
        assert meta['orchestration']['mode'] == 'auto'
    finally:
        active_mod.is_mws_gpt_active = prev


def test_parse_export_intent_turkish_pdf_png():
    assert parse_export_intent('bunu pdf formatına çevir') is not None
    assert parse_export_intent('pdf yap').target == 'pdf'
    assert parse_export_intent('png yap').target == 'png'
    assert parse_export_intent("pdf'e çevir") is not None
    assert parse_export_intent('başka formata çevir') is not None
    assert parse_export_intent('farklı formatta ver') is not None
    assert parse_export_intent('png ver') is not None
    assert parse_export_intent('bana pdf nedir tam olarak') is None


def test_export_blocks_web_search():
    assert export_intent_blocks_web_search('pdf yap')
    assert not export_intent_blocks_web_search('hello')


def test_classify_modality_export():
    m, _ = classify_task_modality(message_text='jpg yap', attachments=set(), input_mode=None)
    assert m == 'export'


def test_auto_workflow_export_is_single():
    cfg = SimpleNamespace(MWS_AUTO_MULTI_MODEL=True)
    wf = build_auto_workflow(
        decision={'modality': 'export', 'model_id': 'llama-3.3-70b-instruct'},
        available={'llama-3.3-70b-instruct'},
        config=cfg,
        message_text='pdf yap',
        attachments=set(),
    )
    assert wf['kind'] == 'single'


def test_pick_auto_target_export():
    mid, w = pick_auto_target_model('export', {'llama-3.3-70b-instruct', 'qwen-image'})
    assert mid == 'llama-3.3-70b-instruct'
    assert w is None


def test_estimate_complexity_turkish_hard():
    c, _ = estimate_complexity(message_text='Bu teoremi adım adım kanıtla', modality='text', attachments=set())
    assert c == 'hard'


def test_extract_file_id_from_relative_api_path():
    """Keep in sync with export_formats._extract_openwebui_file_id (no heavy import here)."""
    import re

    def extract_file_id(s: str) -> str | None:
        m = re.search(
            r'/files/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',
            s,
            re.I,
        )
        return m.group(1) if m else None

    uid = '768b6e57-0866-4800-b3cc-51310806a6ae'
    assert extract_file_id(f'/api/v1/files/{uid}/content') == uid
    assert extract_file_id(f'https://localhost:8080/api/v1/files/{uid}/content') == uid
