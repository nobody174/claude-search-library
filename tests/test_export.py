import json

import pytest

from src.export import export_session, session_to_markdown
from src.storage import Storage

SAMPLE_SESSION = {
    "id": "sess-1",
    "source": "claude-ai",
    "device": "desktop",
    "title": "Minecraft Mod Debugging",
    "created_at": "2026-07-31T14:22:00+00:00",
    "updated_at": "2026-07-31T14:30:00+00:00",
    "duration_seconds": 480,
    "message_count": 2,
    "user_message_count": 1,
    "assistant_message_count": 1,
    "raw_file_path": None,
    "summary_file_path": None,
    "content_hash": "abc123",
    "processed_at": None,
    "status": "processed",
    "review_reason": None,
    "synced_at": None,
    "sync_version": 1,
}

SAMPLE_SUMMARY = {
    "tldr": "Fixed the mod crash.",
    "learnings": ["Check stack traces"],
    "patterns": ["Reproduce then bisect"],
    "tags": ["minecraft"],
    "topic_categories": ["minecraft-modding"],
}


def test_session_to_markdown_without_summary():
    md = session_to_markdown(SAMPLE_SESSION, None)
    assert "# Minecraft Mod Debugging" in md
    assert "sess-1" in md
    assert "Raw conversation text is unavailable" in md


def test_session_to_markdown_with_summary_and_messages(tmp_path):
    raw_file = tmp_path / "sess-1.json"
    raw_file.write_text(
        json.dumps({"messages": [{"role": "user", "content": "Why does it crash?"},
                                  {"role": "assistant", "content": "Check the stack trace."}]}),
        encoding="utf-8",
    )
    session = dict(SAMPLE_SESSION, raw_file_path=str(raw_file))

    md = session_to_markdown(session, SAMPLE_SUMMARY)

    assert "Fixed the mod crash." in md
    assert "Check stack traces" in md
    assert "### User" in md
    assert "Why does it crash?" in md
    assert "### Assistant" in md


def test_export_session_end_to_end(tmp_path):
    db_path = str(tmp_path / "test.db")
    with Storage(db_path) as db:
        db.insert_session(SAMPLE_SESSION)
        db.store_summary("sess-1", SAMPLE_SUMMARY)

    output_path = tmp_path / "session.md"
    result_path = export_session("sess-1", output_path=str(output_path), db_path=db_path)

    assert result_path == str(output_path)
    content = output_path.read_text(encoding="utf-8")
    assert "# Minecraft Mod Debugging" in content
    assert "Fixed the mod crash." in content


def test_export_session_missing_raises(tmp_path):
    db_path = str(tmp_path / "test.db")
    with Storage(db_path):
        pass

    with pytest.raises(ValueError):
        export_session("does-not-exist", db_path=db_path)
