"""Tests for src/collector.py:collect_from_cowork() and its helpers.

Unlike collect_from_claude_desktop() (real Chromium IndexedDB/V8 binary
format), Cowork sessions are discovered to be plain JSONL - the exact same
format collect_from_claude_code() already reads - just nested under the
desktop app's local-agent-mode-sessions/ tree. So this CAN and does build
a real synthetic fixture end-to-end, including a regression test for the
real long-path bug found against actual data (see CHANGELOG.md): Cowork's
real nested directory structure exceeds Windows' 260-char MAX_PATH, which
silently breaks plain pathlib glob/iterdir with no path-length-related
error message.
"""
import json

from src import collector


def _write_cowork_session(root, account_id, org_id, session_uuid, title, created_at_ms, messages, extra_dirname=""):
    """Build one local_<uuid>[.json] pair matching the real on-disk shape."""
    base = root / account_id / org_id
    base.mkdir(parents=True, exist_ok=True)

    meta = {
        "sessionId": session_uuid,
        "title": title,
        "createdAt": created_at_ms,
    }
    (base / f"local_{session_uuid}.json").write_text(json.dumps(meta), encoding="utf-8")

    session_dir = base / f"local_{session_uuid}"
    # Real paths use a sanitized-full-path directory name here, which is
    # what pushes the total path past MAX_PATH - extra_dirname lets tests
    # opt into reproducing that length deliberately. Creating (not just
    # later reading) such a path hits the same MAX_PATH wall, so the
    # fixture itself needs the long-path prefix too.
    project_dir = collector._winlongpath(session_dir / ".claude" / "projects" / f"outputs{extra_dirname}")
    project_dir.mkdir(parents=True, exist_ok=True)

    jsonl_lines = [
        {"type": "queue-operation", "operation": "enqueue"},
        {"type": "ai-title", "aiTitle": "ignored - metadata title wins", "sessionId": session_uuid},
    ]
    for i, (role, text) in enumerate(messages):
        jsonl_lines.append({
            "type": role,
            "sessionId": session_uuid,
            "timestamp": f"2026-07-26T09:4{i}:00Z",
            "message": {"role": role, "content": [{"type": "text", "text": text}]},
        })
    transcript_path = project_dir / f"{session_uuid}.jsonl"
    transcript_path.write_text("\n".join(json.dumps(line) for line in jsonl_lines), encoding="utf-8")

    return session_dir


def test_collect_from_cowork_converts_real_session(tmp_path, monkeypatch):
    monkeypatch.setattr(
        collector.Path, "home", classmethod(lambda cls: tmp_path / "home")
    )
    root = tmp_path / "sessions"
    _write_cowork_session(
        root, "acct-1", "org-1", "5051385b-a21b-4024-8218-2cdbcce5668f",
        title="NEXA and Shelly plug comparison",
        created_at_ms=1785058822939,  # 2026-07-26T09:40:22.939Z
        messages=[("user", "Compare NEXA and Shelly plugs"), ("assistant", "Here's the comparison...")],
    )

    sessions = collector.collect_from_cowork(str(root))

    assert len(sessions) == 1
    session = sessions[0]
    assert session["id"] == "5051385b-a21b-4024-8218-2cdbcce5668f"
    assert session["source"] == "cowork"
    # Metadata title/createdAt must win over the transcript's own ai-title line.
    assert session["title"] == "NEXA and Shelly plug comparison"
    assert session["created_at"].startswith("2026-07-26T09:40:22")
    assert session["message_count"] == 2


def test_collect_from_cowork_missing_folder_returns_empty(tmp_path):
    missing = tmp_path / "cowork-cache"
    assert collector.collect_from_cowork(str(missing)) == []


def test_collect_from_cowork_skips_metadata_without_transcript(tmp_path):
    root = tmp_path / "sessions"
    base = root / "acct-1" / "org-1"
    base.mkdir(parents=True)
    (base / "local_orphan-uuid.json").write_text(
        json.dumps({"title": "No transcript dir for this one", "createdAt": 1785058822939}),
        encoding="utf-8",
    )
    # No local_orphan-uuid/ directory created - session was archived/GC'd
    # server-side but the metadata sidecar is still on disk.

    assert collector.collect_from_cowork(str(root)) == []


def test_collect_from_cowork_handles_paths_past_windows_max_path(tmp_path):
    """Regression test for the real bug found 2026-08-04: a real Cowork
    session's nested path (local-agent-mode-sessions/<acct>/<org>/
    local_<uuid>/.claude/projects/<sanitized-dirname>/<uuid>.jsonl) measured
    441 characters on the real machine - well past Windows' 260-char
    MAX_PATH. Plain pathlib iterdir()/glob() silently returned nothing
    (not an error mentioning path length) instead of finding the real
    file. collect_from_cowork() must use the \\\\?\\ long-path prefix
    internally to actually find it. This test reproduces a comparably
    long nested directory name to catch a regression back to plain glob.
    """
    root = tmp_path / "sessions"
    long_dirname = "-" + "x" * 220  # padding to push the full path past 260 chars
    session_dir = _write_cowork_session(
        root, "acct-1", "org-1", "long-path-uuid",
        title="Long path regression session",
        created_at_ms=1785058822939,
        messages=[("user", "hello"), ("assistant", "hi")],
        extra_dirname=long_dirname,
    )
    full_jsonl_path = session_dir / ".claude" / "projects" / f"outputs{long_dirname}" / "long-path-uuid.jsonl"
    assert len(str(full_jsonl_path)) > 260  # sanity: fixture genuinely exceeds MAX_PATH

    sessions = collector.collect_from_cowork(str(root))

    assert len(sessions) == 1
    assert sessions[0]["title"] == "Long path regression session"


def test_winlongpath_prefixes_on_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(collector.platform, "system", lambda: "Windows")
    result = collector._winlongpath(tmp_path)
    assert str(result).startswith("\\\\?\\")
    assert str(result).endswith(str(tmp_path.resolve()))


def test_winlongpath_noop_on_non_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(collector.platform, "system", lambda: "Linux")
    assert collector._winlongpath(tmp_path) == tmp_path


def test_winlongpath_does_not_double_prefix(monkeypatch):
    monkeypatch.setattr(collector.platform, "system", lambda: "Windows")
    from pathlib import Path

    already = Path("\\\\?\\C:\\some\\path")
    assert collector._winlongpath(already) == already
