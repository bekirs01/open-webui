"""Cross-chat snapshot formatting and meta merge behavior."""

from open_webui.models.chat_context_snapshots import ChatContextSnapshotModel
from open_webui.utils.cross_chat.prompt_block import format_snapshot_for_prompt


def test_format_snapshot_compact():
    m = ChatContextSnapshotModel(
        id='1',
        user_id='u',
        chat_id='c',
        summary='Working on OpenWebUI memory.',
        key_points=['Decision: use snapshots', 'Use LLM for summary'],
        preferences=['Concise answers'],
        ongoing_tasks=['Finish tests'],
        constraints=['No secrets in memory'],
        created_at=1,
        updated_at=1,
    )
    text = format_snapshot_for_prompt(m, max_chars=8000)
    assert 'OpenWebUI' in text
    assert 'Decision:' in text
    assert 'Concise' in text


def test_format_snapshot_truncates():
    long_summary = 'x' * 10000
    m = ChatContextSnapshotModel(
        id='1',
        user_id='u',
        chat_id='c',
        summary=long_summary,
        created_at=1,
        updated_at=1,
    )
    text = format_snapshot_for_prompt(m, max_chars=100)
    assert len(text) <= 100
