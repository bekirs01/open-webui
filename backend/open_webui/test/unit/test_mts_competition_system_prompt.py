"""MTS yarışma sistem promptu enjeksiyonu (birim)."""

import os

from open_webui.utils.mts_competition_system_prompt import (
    get_mts_competition_prompt_text,
    maybe_prepend_mts_system_message,
)


def test_maybe_prepend_disabled_by_default(monkeypatch):
    monkeypatch.delenv('MTS_COMPETITION_SYSTEM_PROMPT_ENABLED', raising=False)
    msgs = [{'role': 'user', 'content': 'hi'}]
    assert maybe_prepend_mts_system_message(msgs) == msgs


def test_maybe_prepend_inserts_system_when_enabled(monkeypatch):
    monkeypatch.setenv('MTS_COMPETITION_SYSTEM_PROMPT_ENABLED', 'true')
    monkeypatch.delenv('MTS_COMPETITION_SYSTEM_PROMPT', raising=False)
    monkeypatch.delenv('MTS_COMPETITION_SYSTEM_PROMPT_FILE', raising=False)
    msgs = [{'role': 'system', 'content': 'local'}, {'role': 'user', 'content': 'hi'}]
    out = maybe_prepend_mts_system_message(msgs)
    assert out[0]['role'] == 'system'
    assert 'MTS' in out[0]['content']
    assert out[1]['content'] == 'local'


def test_prompt_override_env(monkeypatch):
    monkeypatch.setenv('MTS_COMPETITION_SYSTEM_PROMPT', 'CUSTOM-RULES')
    monkeypatch.delenv('MTS_COMPETITION_SYSTEM_PROMPT_FILE', raising=False)
    assert get_mts_competition_prompt_text() == 'CUSTOM-RULES'


def test_prompt_restores_after_override(monkeypatch):
    monkeypatch.delenv('MTS_COMPETITION_SYSTEM_PROMPT', raising=False)
    monkeypatch.delenv('MTS_COMPETITION_SYSTEM_PROMPT_FILE', raising=False)
    t = get_mts_competition_prompt_text()
    assert len(t) > 50
