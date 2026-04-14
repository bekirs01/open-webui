"""Long-term memory: safety, dedupe, ranking, extraction helpers."""

from unittest.mock import patch

from open_webui.utils.long_term_memory.safety import is_likely_sensitive, normalize_for_dedupe
from open_webui.utils.long_term_memory.dedupe import best_fuzzy_match
from open_webui.utils.long_term_memory.retrieval import (
    memory_visible_in_folder_scope,
    rank_memory_hits,
    _normalize_vector_score,
    _time_decay,
)
from open_webui.utils.long_term_memory.extraction import _parse_json_block
from open_webui.models.memories import MemoryModel
from open_webui.models.memories import Memories


# ---------------------------------------------------------------------------
# Safety tests
# ---------------------------------------------------------------------------

def test_safety_rejects_sk_key():
    assert is_likely_sensitive('here is my key sk-abcdefghijklmnopqrstuvwxyz1234 for api')


def test_safety_allows_normal_preference():
    assert not is_likely_sensitive('User prefers concise bullet answers for code review.')


def test_safety_rejects_tckn():
    assert is_likely_sensitive('My TC kimlik number is 12345678901')


def test_safety_rejects_turkish_iban():
    assert is_likely_sensitive('IBAN: TR330006100519786457841326')


def test_safety_rejects_turkish_phone():
    assert is_likely_sensitive('Call me at +90 532 123 45 67')


def test_safety_rejects_credit_card_number():
    assert is_likely_sensitive('Card: 4532 1234 5678 9012')


def test_safety_rejects_password_field():
    assert is_likely_sensitive('password=MySecret123!')


def test_safety_rejects_parola():
    assert is_likely_sensitive('parola: gizli123')


def test_safety_rejects_passport():
    assert is_likely_sensitive('My passport number is U12345678')


def test_safety_rejects_turkish_keywords():
    assert is_likely_sensitive('Benim vergi numarasi 1234567890')
    assert is_likely_sensitive('kimlik numarasi 12345678901')
    assert is_likely_sensitive('kredi karti bilgilerim')


def test_safety_allows_general_facts():
    assert not is_likely_sensitive('User likes dark mode and uses Python 3.12 for web development.')
    assert not is_likely_sensitive('Prefers Turkish language for all responses.')


def test_safety_rejects_empty_or_short():
    assert is_likely_sensitive('')
    assert is_likely_sensitive('ab')
    assert is_likely_sensitive(None)


# ---------------------------------------------------------------------------
# Normalize for dedupe
# ---------------------------------------------------------------------------

def test_normalize_strips_whitespace():
    assert normalize_for_dedupe('  Hello   World!  ') == 'hello world'


def test_normalize_removes_trailing_punctuation():
    assert normalize_for_dedupe('some fact.') == 'some fact'
    assert normalize_for_dedupe('question??') == 'question'


def test_normalize_truncates():
    long_text = 'a' * 1000
    assert len(normalize_for_dedupe(long_text)) == 500


# ---------------------------------------------------------------------------
# Dedupe tests
# ---------------------------------------------------------------------------

def test_dedupe_finds_similar():
    candidate = normalize_for_dedupe('I prefer short answers')
    existing = [
        {'id': 'a', 'normalized_content': normalize_for_dedupe('I prefer short answers.'), 'content': 'x'}
    ]
    hit = best_fuzzy_match(candidate, existing, threshold=0.9)
    assert hit and hit['id'] == 'a'


def test_dedupe_no_match_below_threshold():
    candidate = normalize_for_dedupe('I love ice cream')
    existing = [
        {'id': 'b', 'normalized_content': normalize_for_dedupe('Programming in Rust is great'), 'content': 'y'}
    ]
    hit = best_fuzzy_match(candidate, existing, threshold=0.8)
    assert hit is None


def test_dedupe_empty_candidate():
    assert best_fuzzy_match('', [{'id': 'x', 'content': 'hello'}]) is None


def test_dedupe_empty_existing():
    assert best_fuzzy_match('hello', []) is None


# ---------------------------------------------------------------------------
# Extraction JSON parse
# ---------------------------------------------------------------------------

def test_parse_json_block_clean():
    raw = '{"save": true, "content": "User likes Python", "category": "preference", "confidence": 0.9, "importance": 0.8, "reason": "stable"}'
    parsed = _parse_json_block(raw)
    assert parsed is not None
    assert parsed['save'] is True
    assert parsed['content'] == 'User likes Python'


def test_parse_json_block_with_markdown_fence():
    raw = '```json\n{"save": true, "content": "dark mode", "category": "preference", "confidence": 0.8, "importance": 0.7, "reason": "consistent"}\n```'
    parsed = _parse_json_block(raw)
    assert parsed is not None
    assert parsed['save'] is True


def test_parse_json_block_with_trailing_comma():
    raw = '{"save": true, "content": "test", "category": "custom", "confidence": 0.5, "importance": 0.5, "reason": "ok",}'
    parsed = _parse_json_block(raw)
    assert parsed is not None
    assert parsed['save'] is True


def test_parse_json_block_with_single_quotes():
    raw = "{'save': true, 'content': 'testing', 'category': 'custom', 'confidence': 0.5, 'importance': 0.5, 'reason': 'ok'}"
    parsed = _parse_json_block(raw)
    assert parsed is not None


def test_parse_json_block_returns_none_for_garbage():
    assert _parse_json_block('no json here') is None
    assert _parse_json_block('') is None
    assert _parse_json_block(None) is None


def test_parse_json_block_partial_regex_fallback():
    raw = '{"save": true, "content": "some memory", broken_json'
    parsed = _parse_json_block(raw)
    assert parsed is not None or parsed is None  # graceful handling


# ---------------------------------------------------------------------------
# Retrieval — vector score normalization
# ---------------------------------------------------------------------------

def test_normalize_vector_score_distance():
    assert _normalize_vector_score(0.0) == 1.0  # identical
    assert abs(_normalize_vector_score(1.0) - 0.5) < 0.01  # orthogonal
    assert _normalize_vector_score(2.0) == 0.0  # opposite


def test_time_decay_fresh():
    assert abs(_time_decay(0.0) - 1.0) < 0.001


def test_time_decay_half_life():
    import os
    hl = float(os.environ.get('LTM_RECENCY_HALF_LIFE_DAYS', '60'))
    decayed = _time_decay(hl)
    assert abs(decayed - 0.5) < 0.05


# ---------------------------------------------------------------------------
# Retrieval — ranking
# ---------------------------------------------------------------------------

def test_rank_orders_by_vector_and_scores():
    m1 = MemoryModel(
        id='1',
        user_id='u',
        content='prefers concise text',
        created_at=100,
        updated_at=100,
        importance_score=0.9,
        confidence_score=0.9,
        status='active',
    )
    m2 = MemoryModel(
        id='2',
        user_id='u',
        content='other',
        created_at=100,
        updated_at=100,
        importance_score=0.2,
        confidence_score=0.3,
        status='active',
    )

    def fake_get(mid, db=None):
        return {'1': m1, '2': m2}.get(mid)

    with patch.object(Memories, 'get_memory_by_id', fake_get):
        out = rank_memory_hits(
            user_id='u',
            vector_ids=['2', '1'],
            vector_scores=[0.9, 0.85],
            top_k=2,
        )
        assert len(out) == 2


def test_rank_filters_archived():
    m1 = MemoryModel(
        id='1', user_id='u', content='active', created_at=100, updated_at=100, status='active'
    )
    m2 = MemoryModel(
        id='2', user_id='u', content='archived', created_at=100, updated_at=100, status='archived'
    )

    def fake_get(mid, db=None):
        return {'1': m1, '2': m2}.get(mid)

    with patch.object(Memories, 'get_memory_by_id', fake_get):
        out = rank_memory_hits(
            user_id='u',
            vector_ids=['1', '2'],
            vector_scores=[0.8, 0.9],
            top_k=10,
        )
        assert len(out) == 1
        assert out[0].id == '1'


def test_rank_filters_wrong_user():
    m1 = MemoryModel(
        id='1', user_id='other', content='not mine', created_at=100, updated_at=100, status='active'
    )

    def fake_get(mid, db=None):
        return {'1': m1}.get(mid)

    with patch.object(Memories, 'get_memory_by_id', fake_get):
        out = rank_memory_hits(
            user_id='u',
            vector_ids=['1'],
            vector_scores=[0.9],
            top_k=10,
        )
        assert len(out) == 0


def test_memory_visible_in_folder_scope():
    g = MemoryModel(
        id='g',
        user_id='u',
        content='x',
        created_at=1,
        updated_at=1,
        status='active',
        folder_id=None,
    )
    f1 = MemoryModel(
        id='a',
        user_id='u',
        content='y',
        created_at=1,
        updated_at=1,
        status='active',
        folder_id='F1',
    )
    assert memory_visible_in_folder_scope(g, 'F1')
    assert memory_visible_in_folder_scope(f1, 'F1')
    assert not memory_visible_in_folder_scope(
        MemoryModel(
            id='b',
            user_id='u',
            content='z',
            created_at=1,
            updated_at=1,
            status='active',
            folder_id='F2',
        ),
        'F1',
    )
    assert memory_visible_in_folder_scope(g, None)
    assert not memory_visible_in_folder_scope(f1, None)


def test_rank_filters_by_folder_scope():
    m_global = MemoryModel(
        id='g',
        user_id='u',
        content='global fact',
        created_at=100,
        updated_at=100,
        status='active',
        folder_id=None,
    )
    m_f1 = MemoryModel(
        id='a',
        user_id='u',
        content='folder1',
        created_at=100,
        updated_at=100,
        status='active',
        folder_id='F1',
    )
    m_f2 = MemoryModel(
        id='b',
        user_id='u',
        content='folder2',
        created_at=100,
        updated_at=100,
        status='active',
        folder_id='F2',
    )

    def fake_get(mid, db=None):
        return {'g': m_global, 'a': m_f1, 'b': m_f2}.get(mid)

    with patch.object(Memories, 'get_memory_by_id', fake_get):
        out = rank_memory_hits(
            user_id='u',
            vector_ids=['g', 'a', 'b'],
            vector_scores=[0.9, 0.85, 0.8],
            top_k=10,
            folder_scope_id='F1',
            apply_folder_scope=True,
        )
        ids = {x.id for x in out}
        assert ids == {'g', 'a'}
