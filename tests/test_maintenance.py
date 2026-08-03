from datetime import datetime, timedelta, timezone

from src.maintenance import find_prunable_sessions, prune_sessions
from src.storage import Storage


def _session_row(session_id: str, created_at: str, raw_file_path) -> dict:
    return {
        "id": session_id, "source": "claude-ai", "device": "desktop", "title": "t",
        "created_at": created_at, "updated_at": created_at,
        "duration_seconds": 0, "message_count": 1, "user_message_count": 1,
        "assistant_message_count": 0, "raw_file_path": raw_file_path, "summary_file_path": None,
        "content_hash": session_id, "processed_at": None, "status": "processed",
        "review_reason": None, "synced_at": None, "sync_version": 1,
    }


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def test_find_prunable_sessions_only_returns_old_ones_with_files(tmp_path):
    db_path = str(tmp_path / "test.db")
    old_file = tmp_path / "old.json"
    old_file.write_text("{}", encoding="utf-8")
    recent_file = tmp_path / "recent.json"
    recent_file.write_text("{}", encoding="utf-8")

    with Storage(db_path) as db:
        db.insert_session(_session_row("old-sess", _iso_days_ago(400), str(old_file)))
        db.insert_session(_session_row("recent-sess", _iso_days_ago(10), str(recent_file)))
        db.insert_session(_session_row("already-pruned", _iso_days_ago(500), None))

    candidates = find_prunable_sessions(365, db_path=db_path)

    assert [c["id"] for c in candidates] == ["old-sess"]


def test_prune_sessions_dry_run_does_not_delete(tmp_path):
    db_path = str(tmp_path / "test.db")
    old_file = tmp_path / "old.json"
    old_file.write_text("hello world", encoding="utf-8")

    with Storage(db_path) as db:
        db.insert_session(_session_row("old-sess", _iso_days_ago(400), str(old_file)))

    result = prune_sessions(older_than_days=365, dry_run=True, db_path=db_path)

    assert result == {"candidates": 1, "pruned": 0, "freed_bytes": len("hello world"), "dry_run": True}
    assert old_file.exists()

    with Storage(db_path) as db:
        session = db.get_session("old-sess")
    assert session["raw_file_path"] == str(old_file)


def test_prune_sessions_deletes_raw_file_and_clears_path_but_keeps_session(tmp_path):
    db_path = str(tmp_path / "test.db")
    old_file = tmp_path / "old.json"
    old_file.write_text("hello world", encoding="utf-8")

    with Storage(db_path) as db:
        db.insert_session(_session_row("old-sess", _iso_days_ago(400), str(old_file)))
        db.store_summary("old-sess", {"tldr": "kept summary", "learnings": [], "patterns": [], "tags": []})

    result = prune_sessions(older_than_days=365, dry_run=False, db_path=db_path)

    assert result["pruned"] == 1
    assert not old_file.exists()

    with Storage(db_path) as db:
        session = db.get_session("old-sess")
        summary = db.get_summary("old-sess")

    assert session is not None  # session row survives pruning
    assert session["raw_file_path"] is None
    assert summary["tldr"] == "kept summary"  # summary survives pruning


def test_prune_sessions_ignores_recent_sessions(tmp_path):
    db_path = str(tmp_path / "test.db")
    recent_file = tmp_path / "recent.json"
    recent_file.write_text("hello", encoding="utf-8")

    with Storage(db_path) as db:
        db.insert_session(_session_row("recent-sess", _iso_days_ago(10), str(recent_file)))

    result = prune_sessions(older_than_days=365, dry_run=False, db_path=db_path)

    assert result == {"candidates": 0, "pruned": 0, "freed_bytes": 0, "dry_run": False}
    assert recent_file.exists()
