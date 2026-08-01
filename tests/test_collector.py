import json
from pathlib import Path

import pytest

from src import collector


SAMPLE_EXPORT = {
    "id": "chat-uuid-1",
    "title": "Minecraft Mod Debugging",
    "created_at": "2026-07-31T14:22:00+00:00",
    "messages": [
        {"role": "user", "content": "Why is my mod crashing?", "timestamp": "2026-07-31T14:22:05+00:00"},
        {"role": "assistant", "content": "Let's check the stack trace.", "timestamp": "2026-07-31T14:22:15+00:00"},
    ],
}


@pytest.fixture
def export_folder(tmp_path):
    folder = tmp_path / "exports"
    folder.mkdir()
    (folder / "session1.json").write_text(json.dumps(SAMPLE_EXPORT), encoding="utf-8")
    (folder / "broken.json").write_text("{not valid json", encoding="utf-8")
    return folder


def test_normalize_session_basic():
    normalized = collector.normalize_session(SAMPLE_EXPORT, source="claude-ai", device="desktop", raw_path="x.json")

    assert normalized["id"] == "chat-uuid-1"
    assert normalized["source"] == "claude-ai"
    assert normalized["title"] == "Minecraft Mod Debugging"
    assert normalized["message_count"] == 2
    assert normalized["user_message_count"] == 1
    assert normalized["assistant_message_count"] == 1
    assert normalized["duration_seconds"] == 15
    assert normalized["device"] == "desktop"
    assert normalized["raw_path"] == "x.json"
    assert normalized["messages"][0]["role"] == "user"
    assert normalized["messages"][0]["tokens_approx"] > 0


def test_normalize_session_generates_id_when_missing():
    raw = dict(SAMPLE_EXPORT)
    raw.pop("id")
    normalized = collector.normalize_session(raw, source="local", device="desktop")
    assert normalized["id"]


def test_collect_from_claude_ai_reads_valid_files_and_skips_broken(export_folder):
    sessions = collector.collect_from_claude_ai(str(export_folder))
    assert len(sessions) == 1
    assert sessions[0]["source"] == "claude-ai"
    assert sessions[0]["title"] == "Minecraft Mod Debugging"


def test_collect_from_claude_ai_missing_folder_returns_empty(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert collector.collect_from_claude_ai(str(missing)) == []


def test_collect_from_local(export_folder):
    sessions = collector.collect_from_local(str(export_folder))
    assert len(sessions) == 1
    assert sessions[0]["source"] == "local"


def test_collect_from_vscode_missing_extensions_dir(tmp_path):
    missing = tmp_path / "no-extensions"
    assert collector.collect_from_vscode(str(missing)) == []


def test_collect_from_vscode_finds_history(tmp_path):
    ext_dir = tmp_path / "anthropic.claude-vscode-1.2.3" / "chat_history"
    ext_dir.mkdir(parents=True)
    (ext_dir / "session.json").write_text(json.dumps(SAMPLE_EXPORT), encoding="utf-8")

    sessions = collector.collect_from_vscode(str(tmp_path))
    assert len(sessions) == 1
    assert sessions[0]["source"] == "vscode"


def test_collect_from_cowork_missing_folder_returns_empty(tmp_path):
    missing = tmp_path / "cowork-cache"
    assert collector.collect_from_cowork(str(missing)) == []


def test_collect_all_aggregates_and_counts_errors(monkeypatch, export_folder, tmp_path):
    empty = tmp_path / "empty"
    db_path = str(tmp_path / "test.db")

    sample_sessions = collector.collect_from_local(str(export_folder))

    monkeypatch.setattr(collector, "collect_from_claude_ai", lambda folder: sample_sessions)
    monkeypatch.setattr(collector, "collect_from_vscode", lambda path: [])
    monkeypatch.setattr(collector, "collect_from_cowork", lambda path: [])

    def failing_local(folder):
        raise RuntimeError("boom")

    monkeypatch.setattr(collector, "collect_from_local", failing_local)

    result = collector.collect_all(claude_ai_folder=str(export_folder), local_folder=str(empty), db_path=db_path)

    assert result["errors"] == 1
    assert result["total"] == 1
    assert result["new"] == 1


def test_collect_all_persists_sessions_to_storage(tmp_path):
    """Regression test: collect_all() must actually write collected sessions
    to the database, not just report counts. This was previously broken —
    collect_all() computed a 'new' count but never called Storage at all,
    so cli.py collect silently discarded every session it claimed to import.
    """
    from src.storage import Storage

    export_folder = tmp_path / "exports"
    export_folder.mkdir()
    (export_folder / "session1.json").write_text(json.dumps(SAMPLE_EXPORT), encoding="utf-8")

    db_path = str(tmp_path / "test.db")
    empty = tmp_path / "empty"

    result = collector.collect_all(
        claude_ai_folder=str(export_folder),
        vscode_extensions_path=str(empty),
        cowork_path=str(empty),
        local_folder=str(empty),
        db_path=db_path,
    )

    assert result["new"] == 1

    with Storage(db_path) as db:
        sessions = db.get_all_sessions()
        assert len(sessions) == 1
        assert sessions[0]["id"] == "chat-uuid-1"
        assert sessions[0]["title"] == "Minecraft Mod Debugging"
        assert sessions[0]["source"] == "claude-ai"
        assert sessions[0]["status"] == "new"
        assert sessions[0]["content_hash"] is not None


def test_collect_all_recollecting_same_content_is_noop(tmp_path):
    """Re-running collect on the same export twice should not create a
    duplicate row - content-hash deduplication should kick in."""
    from src.storage import Storage

    export_folder = tmp_path / "exports"
    export_folder.mkdir()
    (export_folder / "session1.json").write_text(json.dumps(SAMPLE_EXPORT), encoding="utf-8")

    db_path = str(tmp_path / "test.db")
    empty = tmp_path / "empty"

    kwargs = dict(
        claude_ai_folder=str(export_folder),
        vscode_extensions_path=str(empty),
        cowork_path=str(empty),
        local_folder=str(empty),
        db_path=db_path,
    )

    first = collector.collect_all(**kwargs)
    second = collector.collect_all(**kwargs)

    assert first["new"] == 1
    assert second["new"] == 0  # same content, already stored

    with Storage(db_path) as db:
        assert db.get_session_count() == 1


def test_collect_all_stored_hash_matches_reread_of_raw_file(tmp_path):
    """Regression test: the content_hash stored during collection must equal
    compute_session_hash() re-run on the raw file re-read from disk later
    (exactly what verify_archive()'s hash check does). This was previously
    broken: collect_all() hashed the *normalized* session dict (which adds
    tokens_approx and backfills timestamp per message, and never has a
    'source' field matching what verify_archive re-reads), so every single
    collected session failed its own integrity check the moment
    verify_archive() ran, even with zero real corruption.
    """
    from src.storage import compute_session_hash, Storage

    export_folder = tmp_path / "exports"
    export_folder.mkdir()
    export_path = export_folder / "session1.json"
    export_path.write_text(json.dumps(SAMPLE_EXPORT), encoding="utf-8")

    db_path = str(tmp_path / "test.db")
    empty = tmp_path / "empty"

    collector.collect_all(
        claude_ai_folder=str(export_folder),
        vscode_extensions_path=str(empty),
        cowork_path=str(empty),
        local_folder=str(empty),
        db_path=db_path,
    )

    with Storage(db_path) as db:
        session = db.get_all_sessions()[0]

    with open(session["raw_file_path"], encoding="utf-8") as f:
        raw = json.load(f)
    recomputed_hash = compute_session_hash(raw)

    assert session["content_hash"] == recomputed_hash


def test_watch_runs_fixed_number_of_iterations(monkeypatch):
    calls = []
    monkeypatch.setattr(collector, "collect_all", lambda: calls.append(1) or {"new": 0, "errors": 0, "total": 0})
    monkeypatch.setattr(collector.time, "sleep", lambda s: None)

    collector.watch(interval=0, iterations=3)

    assert len(calls) == 3
