import json

from src import collector


def _write_transcript(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")


def test_collect_from_claude_code_converts_transcript(tmp_path, monkeypatch):
    export_home = tmp_path / "home"
    monkeypatch.setattr(collector.Path, "home", classmethod(lambda cls: export_home))

    projects_dir = tmp_path / "projects"
    session_id = "sess-abc"
    transcript = projects_dir / "my-project" / f"{session_id}.jsonl"
    _write_transcript(transcript, [
        {"type": "queue-operation", "operation": "enqueue"},
        {"type": "ai-title", "aiTitle": "Fix the bug", "sessionId": session_id},
        {
            "type": "user",
            "sessionId": session_id,
            "timestamp": "2026-08-01T10:00:00Z",
            "message": {"role": "user", "content": [{"type": "text", "text": "Why does it crash?"}]},
        },
        {
            "type": "assistant",
            "sessionId": session_id,
            "timestamp": "2026-08-01T10:00:05Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "hmm"},
                    {"type": "text", "text": "Check the stack trace."},
                ],
            },
        },
        {
            "type": "assistant",
            "sessionId": session_id,
            "timestamp": "2026-08-01T10:00:10Z",
            "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Bash"}]},
        },
    ])

    sessions = collector.collect_from_claude_code(str(projects_dir))

    assert len(sessions) == 1
    session = sessions[0]
    assert session["id"] == session_id
    assert session["source"] == "claude-code"
    assert session["title"] == "Fix the bug"
    assert session["message_count"] == 2  # the tool-only turn is dropped
    assert session["messages"][0]["content"] == "Why does it crash?"
    assert session["messages"][1]["content"] == "Check the stack trace."

    out_path = export_home / ".claude-search-library" / "data" / "raw_exports" / "claude-code" / f"{session_id}.json"
    assert out_path.exists()


def test_collect_from_claude_code_missing_dir_returns_empty(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert collector.collect_from_claude_code(str(missing)) == []
