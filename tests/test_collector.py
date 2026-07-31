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

    sample_sessions = collector.collect_from_local(str(export_folder))

    monkeypatch.setattr(collector, "collect_from_claude_ai", lambda folder: sample_sessions)
    monkeypatch.setattr(collector, "collect_from_vscode", lambda path: [])
    monkeypatch.setattr(collector, "collect_from_cowork", lambda path: [])

    def failing_local(folder):
        raise RuntimeError("boom")

    monkeypatch.setattr(collector, "collect_from_local", failing_local)

    result = collector.collect_all(claude_ai_folder=str(export_folder), local_folder=str(empty))

    assert result["errors"] == 1
    assert result["total"] == 1
    assert result["new"] == 1


def test_watch_runs_fixed_number_of_iterations(monkeypatch):
    calls = []
    monkeypatch.setattr(collector, "collect_all", lambda: calls.append(1) or {"new": 0, "errors": 0, "total": 0})
    monkeypatch.setattr(collector.time, "sleep", lambda s: None)

    collector.watch(interval=0, iterations=3)

    assert len(calls) == 3
