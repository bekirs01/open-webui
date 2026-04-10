"""Unit tests for MWS GPT team registry and Auto router (no network)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from open_webui.utils.mws_gpt.registry import classify_task_modality, extract_last_user_text
from open_webui.utils.mws_gpt.router import LEGACY_AUTO_IDS, MWS_AUTO_ID, decide_mws_model, resolve_mws_chat_model
from open_webui.utils.mws_gpt.team_registry import (
    MODEL_PRIMARY_CAPABILITY,
    TEAM_ALLOWLIST,
    get_primary_capability,
    pick_auto_target_model,
)
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
    cfg = SimpleNamespace(MWS_GPT_AUTO_ROUTING=True, MWS_GPT_DEFAULT_TEXT_MODEL='')
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
    cfg = SimpleNamespace(MWS_GPT_AUTO_ROUTING=True, MWS_GPT_DEFAULT_TEXT_MODEL='')
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
    cfg = SimpleNamespace(MWS_GPT_AUTO_ROUTING=True, MWS_GPT_DEFAULT_TEXT_MODEL='')
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
    finally:
        active_mod.is_mws_gpt_active = prev
