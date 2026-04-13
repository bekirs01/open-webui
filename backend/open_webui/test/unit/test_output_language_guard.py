"""Unit tests for reply-language detection and optional sanitization."""

from open_webui.utils.output_language_guard import (
    build_output_language_system_instruction,
    detect_reply_language_profile,
    sanitize_leaked_scripts,
    sanitize_or_aligned_output_items,
)


def test_detect_turkish():
    assert detect_reply_language_profile('1 dolar kaç ruble').code == 'tr'
    assert detect_reply_language_profile('Trump nerelidir ve nerede doğmuştur?').code == 'tr'
    assert detect_reply_language_profile('trump nerelıdır ve nerede dogmustu').code == 'tr'


def test_detect_english():
    assert detect_reply_language_profile('How much is 1 dollar in rubles?').code == 'en'
    assert detect_reply_language_profile('What is the capital of France?').code == 'en'
    assert detect_reply_language_profile('Please explain this in simple terms.').code == 'en'
    # Short prompts with no “the/this/…” but unmistakable English lemmas → still English
    assert detect_reply_language_profile('explain me car shortly').code == 'en'


def test_detect_russian():
    assert detect_reply_language_profile('Трамп откуда и где родился?').code == 'ru'


def test_lock_contains_marker():
    s = build_output_language_system_instruction('Merhaba')
    assert '[OUTPUT_LANGUAGE_LOCK_v1]' in s
    assert 'language' in s.lower() or 'dil' in s.lower() or 'Latin' in s or 'Türkçe' in s


def test_detect_french_latin_generic():
    p = detect_reply_language_profile('Bonjour, comment allez-vous aujourd\'hui ?')
    assert p.code == 'latin_generic'


def test_chinese_user_keeps_cjk_in_sanitize():
    t = '价格明日元'
    assert sanitize_leaked_scripts(t, '今天天气怎么样') == t


def test_chinese_user_strips_cyrillic_leak():
    clean = sanitize_leaked_scripts('价格Кирилл', '你好')
    assert 'К' not in clean


def test_sanitize_strips_cjk_for_turkish():
    dirty = 'Bugün 明 kuru 92.'
    clean = sanitize_leaked_scripts(dirty, 'test için')
    assert '明' not in clean
    assert '92' in clean


def test_sanitize_preserves_code_fence():
    s = 'Metin 明\n```\n明code\n```\nSon 明'
    clean = sanitize_leaked_scripts(s, 'dolar için')
    assert '明' not in clean.split('```')[0]
    assert '明code' in clean


def test_sanitize_or_aligned_mutates_message_text():
    out = [
        {
            'type': 'message',
            'role': 'assistant',
            'content': [{'type': 'output_text', 'text': 'Fiyat 明 TL'}],
        }
    ]
    sanitize_or_aligned_output_items(out, 'bir dolar kaç ruble')
    assert out[0]['content'][0]['text'] == 'Fiyat  TL'


def test_sanitize_skips_when_disabled(monkeypatch):
    monkeypatch.setenv('OUTPUT_LANGUAGE_SANITIZE', 'false')
    monkeypatch.setenv('OUTPUT_TOKEN_SOUP_STRIP', 'false')
    s = 'a明b'
    assert sanitize_leaked_scripts(s, 'x') == s


def test_sanitize_strips_token_soup_paragraph(monkeypatch):
    monkeypatch.delenv('OUTPUT_TOKEN_SOUP_STRIP', raising=False)
    good = (
        'Bekir Suçıkaran hakkında yaklaşık 235 bin abone olduğu söyleniyor. '
        'Kesin sayı için YouTube kanal sayfasına bakın.'
    )
    garbage = (
        'JButton121Exercise SharePointcustom NSMutable/client _EDIT_esLOSE '
        '/**** fooBarBaz quxQuuxCorge ' * 8
    )
    dirty = good + '\n\n' + garbage + '\n\n' + good
    clean = sanitize_leaked_scripts(dirty, 'bekir kaç abone')
    assert 'JButton' not in clean
    assert '235' in clean or 'bakın' in clean
