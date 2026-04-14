"""
Tests for artifact_resolver and export_intent — specifically for the bug:
  User uploads image + "bana bunu jpg olarak ver" → InternalServerError
because artifact was not found in the current user turn.
"""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

# Minimal stubs so we can import artifact_resolver without the full app
_stub_re = ModuleType('re')
sys.modules.setdefault('open_webui', ModuleType('open_webui'))
sys.modules.setdefault('open_webui.utils', ModuleType('open_webui.utils'))
sys.modules.setdefault('open_webui.utils.mws_gpt', ModuleType('open_webui.utils.mws_gpt'))


# ── artifact_resolver tests ──────────────────────────────────────────────

def _load_artifact_resolver():
    import importlib
    return importlib.import_module('open_webui.utils.mws_gpt.artifact_resolver')


def test_image_in_current_user_turn_files():
    """Image attached in same turn as 'bana bunu jpg olarak ver' must be found."""
    mod = _load_artifact_resolver()
    messages = [
        {'role': 'user', 'content': 'merhaba', 'files': []},
        {'role': 'assistant', 'content': 'merhaba!'},
        {
            'role': 'user',
            'content': 'bana bunu jpg olarak ver',
            'files': [
                {'type': 'image', 'url': 'data:image/jpeg;base64,/9j/AAAA', 'id': 'f1'}
            ],
        },
    ]
    result = mod.extract_last_image_artifact_for_export(messages)
    assert result is not None, 'Current user turn image must be found'
    assert result['kind'] == 'image'
    assert result['url'] == 'data:image/jpeg;base64,/9j/AAAA'
    assert result['file_id'] == 'f1'


def test_image_in_content_array_image_url():
    """Image embedded as image_url in content (after files→content injection)."""
    mod = _load_artifact_resolver()
    messages = [
        {
            'role': 'user',
            'content': [
                {'type': 'text', 'text': 'bana bunu jpg olarak ver'},
                {'type': 'image_url', 'image_url': {'url': 'https://example.com/photo.jpg'}},
            ],
        },
    ]
    result = mod.extract_last_image_artifact_for_export(messages)
    assert result is not None, 'image_url in content must be found'
    assert result['kind'] == 'image'
    assert result['url'] == 'https://example.com/photo.jpg'


def test_assistant_image_preferred_over_user_upload():
    """If assistant previously generated an image, that should be preferred."""
    mod = _load_artifact_resolver()
    messages = [
        {
            'role': 'user',
            'content': 'draw a cat',
            'files': [{'type': 'image', 'url': 'user_upload.jpg', 'id': 'u1'}],
        },
        {
            'role': 'assistant',
            'content': 'Here is your cat',
            'files': [{'type': 'image', 'url': 'generated_cat.png', 'id': 'a1'}],
        },
        {'role': 'user', 'content': 'bunu pdf yap'},
    ]
    result = mod.extract_last_image_artifact_for_export(messages)
    assert result is not None
    assert result['url'] == 'generated_cat.png', 'Assistant image should be preferred'


def test_no_messages_returns_none():
    mod = _load_artifact_resolver()
    assert mod.extract_last_image_artifact_for_export([]) is None
    assert mod.extract_last_image_artifact_for_export(None) is None


def test_extract_any_artifact_includes_current_turn():
    """extract_last_artifact_for_export must also find files in the current user message."""
    mod = _load_artifact_resolver()
    messages = [
        {
            'role': 'user',
            'content': 'convert this to pdf',
            'files': [
                {'type': 'image', 'url': 'photo.jpg', 'id': 'f1', 'content_type': 'image/jpeg'}
            ],
        },
    ]
    result = mod.extract_last_artifact_for_export(messages)
    assert result is not None, 'Single-turn image must be found'
    assert result['kind'] == 'image'


# ── export_intent tests ─────────────────────────────────────────────────

def _load_export_intent():
    import importlib
    return importlib.import_module('open_webui.utils.mws_gpt.export_intent')


def test_bana_bunu_jpg_olarak_ver():
    """'bana bunu jpg olarak ver' must be recognized as image_raster / jpeg."""
    mod = _load_export_intent()
    intent = mod.resolve_export_intent('bana bunu jpg olarak ver')
    assert intent is not None, 'Must detect export intent'
    assert intent.kind == 'image_raster'
    assert intent.target in ('jpeg', 'jpg')


def test_png_ver():
    mod = _load_export_intent()
    intent = mod.resolve_export_intent('bunu png ver')
    assert intent is not None
    assert intent.kind == 'image_raster'
    assert intent.target == 'png'


def test_pdf_olarak_ver():
    mod = _load_export_intent()
    intent = mod.resolve_export_intent('bunu pdf olarak ver')
    assert intent is not None
    assert intent.target == 'pdf'


def test_convert_to_jpg():
    mod = _load_export_intent()
    intent = mod.resolve_export_intent('convert to jpg')
    assert intent is not None
    assert intent.kind == 'image_raster'


def test_normal_question_not_export():
    mod = _load_export_intent()
    intent = mod.resolve_export_intent('Merhaba, bugün nasılsın?')
    assert intent is None, 'Normal questions must not be classified as export'


def test_what_is_pdf_not_export():
    mod = _load_export_intent()
    intent = mod.resolve_export_intent('PDF nedir?')
    assert intent is None


# ── collect_turn_files tests ─────────────────────────────────────────────

def test_collect_turn_files_from_content_image_url():
    """When files were popped and injected as image_url, _collect_turn_files must still find them."""
    import importlib
    mod = importlib.import_module('open_webui.utils.mws_gpt.export_pipeline')
    form_data = {
        '_mws_incoming_last_user_files': [],
        'files': [],
        'messages': [
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': 'bana bunu jpg olarak ver'},
                    {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,iVBOR'}},
                ],
            }
        ],
    }
    result = mod._collect_turn_files(form_data)
    assert len(result) >= 1, 'Must find image_url from content'
    assert result[0]['type'] == 'image'
    assert 'iVBOR' in result[0]['url']


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
