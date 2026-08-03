import json

import pytest

from src import collector, orchestration
from src.storage import Storage

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
    return folder


def test_run_collection_rejects_unknown_source():
    with pytest.raises(ValueError):
        orchestration.run_collection(sources=["telepathy"])


def test_run_collection_only_runs_requested_sources(monkeypatch, export_folder, tmp_path):
    db_path = str(tmp_path / "test.db")
    calls = []
    original_claude_ai = collector.collect_from_claude_ai

    def tracked_claude_ai(folder):
        calls.append("claude-ai")
        return original_claude_ai(folder)

    def tracked_vscode(path):
        calls.append("vscode")
        return []

    monkeypatch.setattr(collector, "collect_from_claude_ai", tracked_claude_ai)
    monkeypatch.setattr(collector, "collect_from_vscode", tracked_vscode)

    result = orchestration.run_collection(
        sources=["claude-ai"], claude_ai_folder=str(export_folder), db_path=db_path
    )

    assert calls == ["claude-ai"]
    assert result["sources"] == {"claude-ai": {"collected": 1, "error": None}}
    assert result["new"] == 1


def test_fail_fast_false_continues_past_errors(monkeypatch, export_folder, tmp_path):
    db_path = str(tmp_path / "test.db")
    original_claude_ai = collector.collect_from_claude_ai

    monkeypatch.setattr(collector, "collect_from_claude_ai", lambda folder: original_claude_ai(folder))
    monkeypatch.setattr(collector, "collect_from_vscode", lambda path: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(collector, "collect_from_claude_code", lambda path: [])
    monkeypatch.setattr(collector, "collect_from_claude_desktop", lambda path: [])
    monkeypatch.setattr(collector, "collect_from_cowork", lambda path: [])
    monkeypatch.setattr(collector, "collect_from_local", lambda path: [])

    result = orchestration.run_collection(
        fail_fast=False, claude_ai_folder=str(export_folder), db_path=db_path
    )

    assert result["errors"] == 1
    assert result["new"] == 1
    assert result["sources"]["vscode"]["error"] == "boom"


def test_fail_fast_true_raises_immediately(monkeypatch, export_folder, tmp_path):
    db_path = str(tmp_path / "test.db")
    original_claude_ai = collector.collect_from_claude_ai

    monkeypatch.setattr(collector, "collect_from_claude_ai", lambda folder: original_claude_ai(folder))
    monkeypatch.setattr(collector, "collect_from_vscode", lambda path: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(collector, "collect_from_claude_code", lambda path: [])
    monkeypatch.setattr(collector, "collect_from_claude_desktop", lambda path: [])
    monkeypatch.setattr(collector, "collect_from_cowork", lambda path: [])
    monkeypatch.setattr(collector, "collect_from_local", lambda path: [])

    with pytest.raises(orchestration.CollectionError):
        orchestration.run_collection(fail_fast=True, claude_ai_folder=str(export_folder), db_path=db_path)

    # nothing should have been persisted before the raise on the failing source
    with Storage(db_path) as db:
        assert db.get_session_count() == 0
