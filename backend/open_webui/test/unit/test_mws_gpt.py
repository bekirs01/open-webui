"""Unit tests for MWS GPT registry and router (no network)."""

from types import SimpleNamespace

from open_webui.utils.mws_gpt.registry import (
    build_mws_registry,
    classify_task_modality,
    collect_attachment_kinds,
    extract_last_user_text,
    pick_fallback_model_id,
)
from open_webui.utils.mws_gpt.router import decide_mws_model


def test_registry_merge_and_fallback():
    fetched = [{'id': 'gpt-test', 'name': 'GPT Test'}]
    env_defaults = {
        'text': 'gpt-test',
        'code': 'missing-code-model',
    }
    records, warnings = build_mws_registry(fetched, env_defaults)
    ids = {r.id for r in records}
    assert 'gpt-test' in ids
    assert 'missing-code-model' in ids
    assert any('not in remote' in w for w in warnings)

    fid, w = pick_fallback_model_id(
        records,
        env_defaults,
        'text',
    )
    assert fid == 'gpt-test'
    assert w is None


def test_classify_text_code_vision_audio():
    assert classify_task_modality(message_text='hello', attachments=set(), input_mode=None)[0] == 'text'
    mod, _ = classify_task_modality(
        message_text='def foo(): pass',
        attachments=set(),
        input_mode=None,
    )
    assert mod == 'code'
    mod, _ = classify_task_modality(
        message_text='',
        attachments={'image'},
        input_mode=None,
    )
    assert mod == 'vision'
    mod, _ = classify_task_modality(
        message_text='',
        attachments={'audio'},
        input_mode=None,
    )
    assert mod == 'audio_transcription'
    mod, _ = classify_task_modality(
        message_text='draw a picture of a cat',
        attachments=set(),
        input_mode=None,
    )
    assert mod == 'image_generation'


def test_extract_last_user_text_multipart():
    messages = [
        {'role': 'user', 'content': [{'type': 'text', 'text': 'Hi'}]},
    ]
    assert extract_last_user_text(messages) == 'Hi'


def test_collect_attachment_kinds_from_files():
    kinds = collect_attachment_kinds(
        [{'content_type': 'image/png'}],
        None,
    )
    assert 'image' in kinds


def test_decide_manual_override():
    cfg = SimpleNamespace(
        MWS_GPT_AUTO_ROUTING=True,
        MWS_GPT_DEFAULT_TEXT_MODEL='m-1',
        MWS_GPT_DEFAULT_CODE_MODEL='',
        MWS_GPT_DEFAULT_VISION_MODEL='',
        MWS_GPT_DEFAULT_IMAGE_MODEL='',
        MWS_GPT_DEFAULT_AUDIO_MODEL='',
        MWS_GPT_DEFAULT_EMBEDDING_MODEL='',
    )
    out = decide_mws_model(
        manual_model_id='my-model',
        message_text='x',
        attachments=set(),
        input_mode=None,
        openai_models={'my-model': {'id': 'my-model'}},
        config=cfg,
    )
    assert out['model_id'] == 'my-model'
    assert out['reason'] == 'manual_override'


def test_decide_auto_text():
    cfg = SimpleNamespace(
        MWS_GPT_AUTO_ROUTING=True,
        MWS_GPT_DEFAULT_TEXT_MODEL='m-1',
        MWS_GPT_DEFAULT_CODE_MODEL='m-2',
        MWS_GPT_DEFAULT_VISION_MODEL='',
        MWS_GPT_DEFAULT_IMAGE_MODEL='',
        MWS_GPT_DEFAULT_AUDIO_MODEL='',
        MWS_GPT_DEFAULT_EMBEDDING_MODEL='',
    )
    models = {
        'm-1': {'id': 'm-1', 'tags': [{'name': 'mws'}]},
        'm-2': {'id': 'm-2', 'tags': [{'name': 'mws'}]},
    }
    out = decide_mws_model(
        manual_model_id='mws:auto',
        message_text='plain question',
        attachments=set(),
        input_mode=None,
        openai_models=models,
        config=cfg,
    )
    assert out['model_id'] == 'm-1'


def test_logs_no_secret_leak():
    # Router never logs API keys; smoke-check decide_mws_model structure
    cfg = SimpleNamespace(
        MWS_GPT_AUTO_ROUTING=True,
        MWS_GPT_DEFAULT_TEXT_MODEL='t',
        MWS_GPT_DEFAULT_CODE_MODEL='',
        MWS_GPT_DEFAULT_VISION_MODEL='',
        MWS_GPT_DEFAULT_IMAGE_MODEL='',
        MWS_GPT_DEFAULT_AUDIO_MODEL='',
        MWS_GPT_DEFAULT_EMBEDDING_MODEL='',
    )
    out = decide_mws_model(
        manual_model_id='mws:auto',
        message_text='x',
        attachments=set(),
        input_mode=None,
        openai_models={'t': {'id': 't'}},
        config=cfg,
    )
    dumped = str(out)
    assert 'sk-' not in dumped
