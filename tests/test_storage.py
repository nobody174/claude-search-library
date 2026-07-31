import pytest

from src.storage import Storage


SAMPLE_SESSION = {
    "id": "sess-1",
    "source": "claude-ai",
    "device": "desktop",
    "title": "Minecraft Mod Debugging",
    "created_at": "2026-07-31T14:22:00+00:00",
    "updated_at": "2026-07-31T14:30:00+00:00",
    "duration_seconds": 480,
    "message_count": 4,
    "user_message_count": 2,
    "assistant_message_count": 2,
    "raw_file_path": "/raw/sess-1.json",
    "summary_file_path": None,
    "content_hash": "abc123",
    "processed_at": None,
    "status": "new",
    "review_reason": None,
    "synced_at": None,
    "sync_version": 1,
}

SAMPLE_SUMMARY = {
    "session_tldr": "Fixed the mod crash.",
    "learnings": ["Check stack traces"],
    "patterns": ["Reproduce then bisect"],
    "tags": ["minecraft"],
    "mentioned_tools": ["NeoForge"],
    "mentioned_languages": ["Java"],
    "mentioned_frameworks": ["NeoForge"],
    "estimated_effort_minutes": 30,
    "topic_categories": ["minecraft-modding"],
    "confidence_score": 0.9,
}


@pytest.fixture
def db():
    with Storage(":memory:") as storage:
        yield storage


def test_context_manager_requires_enter():
    storage = Storage(":memory:")
    with pytest.raises(RuntimeError):
        _ = storage.conn


def test_insert_and_get_session(db):
    db.insert_session(SAMPLE_SESSION)
    result = db.get_session("sess-1")
    assert result["id"] == "sess-1"
    assert result["title"] == "Minecraft Mod Debugging"
    assert result["status"] == "new"


def test_get_session_missing_returns_none(db):
    assert db.get_session("does-not-exist") is None


def test_update_session(db):
    db.insert_session(SAMPLE_SESSION)
    updated = db.update_session("sess-1", {"title": "Renamed", "status": "processed"})
    assert updated is True
    result = db.get_session("sess-1")
    assert result["title"] == "Renamed"
    assert result["status"] == "processed"


def test_update_session_ignores_unknown_fields(db):
    db.insert_session(SAMPLE_SESSION)
    updated = db.update_session("sess-1", {"not_a_column": "x"})
    assert updated is False


def test_get_all_sessions(db):
    db.insert_session(SAMPLE_SESSION)
    second = dict(SAMPLE_SESSION, id="sess-2", content_hash="def456")
    db.insert_session(second)
    all_sessions = db.get_all_sessions()
    assert len(all_sessions) == 2
    assert {s["id"] for s in all_sessions} == {"sess-1", "sess-2"}


def test_mark_as_processed(db):
    db.insert_session(SAMPLE_SESSION)
    db.mark_as_processed("sess-1", "processed")
    result = db.get_session("sess-1")
    assert result["status"] == "processed"
    assert result["processed_at"] is not None


def test_mark_for_review(db):
    db.insert_session(SAMPLE_SESSION)
    db.mark_for_review("sess-1", "too many redactions")
    result = db.get_session("sess-1")
    assert result["status"] == "needs_review"
    assert result["review_reason"] == "too many redactions"


def test_store_and_get_summary(db):
    db.insert_session(SAMPLE_SESSION)
    db.store_summary("sess-1", SAMPLE_SUMMARY)
    summary = db.get_summary("sess-1")
    assert summary["tldr"] == "Fixed the mod crash."
    assert summary["learnings"] == ["Check stack traces"]
    assert summary["confidence_score"] == 0.9


def test_store_summary_upserts(db):
    db.insert_session(SAMPLE_SESSION)
    db.store_summary("sess-1", SAMPLE_SUMMARY)
    updated_summary = dict(SAMPLE_SUMMARY, session_tldr="Updated tldr")
    db.store_summary("sess-1", updated_summary)
    result = db.get_summary("sess-1")
    assert result["tldr"] == "Updated tldr"


def test_get_summary_missing_returns_none(db):
    assert db.get_summary("nope") is None


def test_index_session(db):
    db.insert_session(SAMPLE_SESSION)
    result = db.index_session("sess-1", "full searchable text", "minecraft,debugging")
    assert result is True
    row = db.conn.execute("SELECT * FROM search_index WHERE session_id = ?", ("sess-1",)).fetchone()
    assert row["searchable_text"] == "full searchable text"
    assert row["keywords"] == "minecraft,debugging"


def test_index_session_upserts(db):
    db.insert_session(SAMPLE_SESSION)
    db.index_session("sess-1", "first text")
    db.index_session("sess-1", "second text")
    row = db.conn.execute("SELECT * FROM search_index WHERE session_id = ?", ("sess-1",)).fetchone()
    assert row["searchable_text"] == "second text"


def test_log_redaction_and_get(db):
    db.insert_session(SAMPLE_SESSION)
    db.log_redaction("sess-1", "api_key", "abc***xyz", "[API_KEY_REDACTED]", 0.9)
    redactions = db.get_redactions_for_session("sess-1")
    assert len(redactions) == 1
    assert redactions[0]["redaction_type"] == "api_key"
    assert redactions[0]["manually_reviewed"] == 0


def test_get_redactions_for_session_empty(db):
    db.insert_session(SAMPLE_SESSION)
    assert db.get_redactions_for_session("sess-1") == []


def test_check_duplicate(db):
    db.insert_session(SAMPLE_SESSION)
    assert db.check_duplicate("abc123") is True
    assert db.check_duplicate("nonexistent-hash") is False


def test_get_session_count(db):
    assert db.get_session_count() == 0
    db.insert_session(SAMPLE_SESSION)
    assert db.get_session_count() == 1


def test_get_stats(db):
    db.insert_session(SAMPLE_SESSION)
    second = dict(SAMPLE_SESSION, id="sess-2", content_hash="def456", source="vscode", status="processed")
    db.insert_session(second)
    db.log_redaction("sess-1", "email", "a***c", "[EMAIL_REDACTED]", 0.8)

    stats = db.get_stats()
    assert stats["total_sessions"] == 2
    assert stats["by_status"]["new"] == 1
    assert stats["by_status"]["processed"] == 1
    assert stats["by_source"]["claude-ai"] == 1
    assert stats["by_source"]["vscode"] == 1
    assert stats["total_redactions"] == 1


def test_context_manager_closes_connection():
    storage = Storage(":memory:")
    with storage:
        storage.insert_session(SAMPLE_SESSION)
    assert storage._conn is None
