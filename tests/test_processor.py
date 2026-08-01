import json
from types import SimpleNamespace

import anthropic
import pytest

from src import processor
from src.storage import Storage


VALID_SUMMARY = {
    "session_tldr": "Fixed a Minecraft mod crash.",
    "learnings": ["Check stack traces first"],
    "patterns": ["Reproduce, then bisect"],
    "tags": ["minecraft", "debugging"],
    "mentioned_tools": ["NeoForge"],
    "mentioned_languages": ["Java"],
    "mentioned_frameworks": ["NeoForge"],
    "estimated_effort_minutes": 30,
    "topic_categories": ["minecraft-modding"],
    "confidence_score": 0.9,
}

SAMPLE_CHAT = {
    "id": "chat-1",
    "title": "Minecraft Mod Debugging",
    "messages": [
        {"role": "user", "content": "Why does my mod crash on load?"},
        {"role": "assistant", "content": "Let's check the stack trace."},
    ],
}


def _fake_response(text: str):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


@pytest.fixture(autouse=True)
def redirect_log(tmp_path, monkeypatch):
    monkeypatch.setattr(processor, "LOG_PATH", tmp_path / "processing.log")
    monkeypatch.setattr(processor, "NEEDS_REVIEW_DIR", tmp_path / "needs_review")
    monkeypatch.setattr(processor, "SUMMARIES_DIR", tmp_path / "summaries")
    processor.logger.handlers.clear()
    yield


def test_summarize_chat_success(monkeypatch):
    monkeypatch.setattr(
        anthropic.Anthropic,
        "with_options",
        lambda self, **kw: SimpleNamespace(
            messages=SimpleNamespace(
                create=lambda **kwargs: _fake_response(json.dumps(VALID_SUMMARY))
            )
        ),
    )

    result = processor.summarize_chat(SAMPLE_CHAT, api_key="fake-key")
    assert result == VALID_SUMMARY


def test_summarize_chat_retries_on_bad_json_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_create(**kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            return _fake_response("not json")
        return _fake_response(json.dumps(VALID_SUMMARY))

    monkeypatch.setattr(
        anthropic.Anthropic,
        "with_options",
        lambda self, **kw: SimpleNamespace(messages=SimpleNamespace(create=fake_create)),
    )

    result = processor.summarize_chat(SAMPLE_CHAT, api_key="fake-key")
    assert result == VALID_SUMMARY
    assert calls["n"] == 2


def test_summarize_chat_exhausts_retries_raises(monkeypatch):
    monkeypatch.setattr(
        anthropic.Anthropic,
        "with_options",
        lambda self, **kw: SimpleNamespace(
            messages=SimpleNamespace(create=lambda **kwargs: _fake_response("still not json"))
        ),
    )

    with pytest.raises(ValueError):
        processor.summarize_chat(SAMPLE_CHAT, api_key="fake-key")


def test_summarize_chat_invalid_schema_saves_needs_review(monkeypatch, tmp_path):
    incomplete = {"session_tldr": "missing everything else"}
    monkeypatch.setattr(
        anthropic.Anthropic,
        "with_options",
        lambda self, **kw: SimpleNamespace(
            messages=SimpleNamespace(create=lambda **kwargs: _fake_response(json.dumps(incomplete)))
        ),
    )

    with pytest.raises(ValueError):
        processor.summarize_chat(SAMPLE_CHAT, api_key="fake-key")

    review_file = processor.NEEDS_REVIEW_DIR / "chat-1.json"
    assert review_file.exists()


def test_parse_summary_json_strips_markdown_fences():
    fenced = "```json\n" + json.dumps(VALID_SUMMARY) + "\n```"
    assert processor._parse_summary_json(fenced) == VALID_SUMMARY


def test_truncate_to_token_limit_short_text_unchanged():
    text = "short text"
    assert processor._truncate_to_token_limit(text, max_tokens=1000) == text


def test_truncate_to_token_limit_long_text_truncated():
    text = "x" * 10000
    result = processor._truncate_to_token_limit(text, max_tokens=100)
    assert len(result) <= 100 * 4 + len("\n\n[...truncated...]")
    assert result.endswith("[...truncated...]")


def _session_row(session_id, raw_file_path):
    return {
        "id": session_id, "source": "claude-ai", "device": "desktop",
        "title": "Minecraft Mod Debugging", "created_at": "2026-01-01T00:00:00Z", "updated_at": None,
        "duration_seconds": 0, "message_count": 2, "user_message_count": 1,
        "assistant_message_count": 1, "raw_file_path": str(raw_file_path), "summary_file_path": None,
        "content_hash": f"hash-{session_id}", "processed_at": None, "status": "new",
        "review_reason": None, "synced_at": None, "sync_version": 1,
    }


def test_process_batch_rate_limiting(monkeypatch, tmp_path):
    raw_dir = tmp_path / "raw_chats"
    raw_dir.mkdir()
    db_path = str(tmp_path / "test.db")

    session_ids = []
    with Storage(db_path) as db:
        for i in range(3):
            sid = f"chat-{i}"
            session_ids.append(sid)
            chat = dict(SAMPLE_CHAT)
            chat["id"] = sid
            raw_path = raw_dir / f"{sid}.json"
            raw_path.write_text(json.dumps(chat), encoding="utf-8")
            db.insert_session(_session_row(sid, raw_path))

    monkeypatch.setattr(processor, "summarize_chat", lambda chat_dict, api_key: VALID_SUMMARY)
    sleep_calls = []
    monkeypatch.setattr(processor.time, "sleep", lambda s: sleep_calls.append(s))
    monkeypatch.setattr(processor, "MAX_CALLS_PER_MINUTE", 2)

    results = processor.process_batch(session_ids, api_key="fake-key", db_path=db_path)

    assert set(results["succeeded"]) == set(session_ids)
    assert len(sleep_calls) == 1  # rate limit triggered once after 2 calls


def test_process_batch_missing_session_marked_failed(tmp_path):
    db_path = str(tmp_path / "test.db")
    with Storage(db_path):
        pass  # empty DB, no session with this id

    results = processor.process_batch(["does-not-exist"], api_key="fake-key", db_path=db_path)
    assert "does-not-exist" in results["failed"]


def test_process_batch_missing_raw_file_marked_failed(tmp_path):
    db_path = str(tmp_path / "test.db")
    with Storage(db_path) as db:
        db.insert_session(_session_row("chat-1", tmp_path / "does-not-exist.json"))

    results = processor.process_batch(["chat-1"], api_key="fake-key", db_path=db_path)
    assert "chat-1" in results["failed"]


def test_process_batch_writes_summary_sidecar(monkeypatch, tmp_path):
    raw_dir = tmp_path / "raw_chats"
    raw_dir.mkdir()
    raw_path = raw_dir / "chat-1.json"
    raw_path.write_text(json.dumps(SAMPLE_CHAT), encoding="utf-8")
    db_path = str(tmp_path / "test.db")

    with Storage(db_path) as db:
        db.insert_session(_session_row("chat-1", raw_path))

    monkeypatch.setattr(processor, "summarize_chat", lambda chat_dict, api_key: VALID_SUMMARY)

    results = processor.process_batch(["chat-1"], api_key="fake-key", db_path=db_path)

    assert results["succeeded"] == ["chat-1"]
    # Sidecar must NOT be written next to the raw export - collect_all()
    # rescans that folder on every run and would re-ingest it as a fake
    # new session (this was a real bug: see
    # test_process_batch_sidecar_not_written_next_to_raw_export below).
    assert not (raw_dir / "chat-1_summary.json").exists()

    sidecar = processor.SUMMARIES_DIR / "chat-1_summary.json"
    assert sidecar.exists()
    assert json.loads(sidecar.read_text(encoding="utf-8")) == VALID_SUMMARY


def test_process_batch_sidecar_not_written_next_to_raw_export(monkeypatch, tmp_path):
    """Regression test: summary sidecars must live in a directory the
    collector never scans. Previously _save_summary_sidecar() wrote
    <raw_name>_summary.json right next to the original export file, in the
    same folder collect_all() globs for *.json on every run - so running
    `collect` a second time after `process` silently re-ingested each
    session's own generated summary as if it were a brand-new chat export.
    """
    from src import collector

    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    raw_path = export_dir / "chat-1.json"
    raw_path.write_text(json.dumps(SAMPLE_CHAT), encoding="utf-8")
    db_path = str(tmp_path / "test.db")

    with Storage(db_path) as db:
        db.insert_session(_session_row("chat-1", raw_path))

    monkeypatch.setattr(processor, "summarize_chat", lambda chat_dict, api_key: VALID_SUMMARY)
    processor.process_batch(["chat-1"], api_key="fake-key", db_path=db_path)

    # Re-run collect_all against the same export folder - it must find only
    # the original export, not the summary sidecar, regardless of where the
    # sidecar ended up.
    empty = tmp_path / "empty"
    result = collector.collect_all(
        claude_ai_folder=str(export_dir),
        vscode_extensions_path=str(empty),
        cowork_path=str(empty),
        local_folder=str(empty),
        db_path=db_path,
    )
    assert result["total"] == 1  # only the original export, not a re-ingested summary


def test_process_batch_records_summary_file_path(monkeypatch, tmp_path):
    raw_dir = tmp_path / "raw_chats"
    raw_dir.mkdir()
    raw_path = raw_dir / "chat-1.json"
    raw_path.write_text(json.dumps(SAMPLE_CHAT), encoding="utf-8")
    db_path = str(tmp_path / "test.db")

    with Storage(db_path) as db:
        db.insert_session(_session_row("chat-1", raw_path))

    monkeypatch.setattr(processor, "summarize_chat", lambda chat_dict, api_key: VALID_SUMMARY)
    processor.process_batch(["chat-1"], api_key="fake-key", db_path=db_path)

    with Storage(db_path) as db:
        session = db.get_session("chat-1")

    assert session["summary_file_path"] == str(processor.SUMMARIES_DIR / "chat-1_summary.json")


def test_process_batch_populates_search_index(monkeypatch, tmp_path):
    """Regression test: a summarized session must be findable by keyword
    search immediately, not only after a device sync. Previously nothing
    in the collect->process path ever called db.index_session(), so
    search_index stayed empty on any single device that never synced."""
    raw_dir = tmp_path / "raw_chats"
    raw_dir.mkdir()
    raw_path = raw_dir / "chat-1.json"
    raw_path.write_text(json.dumps(SAMPLE_CHAT), encoding="utf-8")
    db_path = str(tmp_path / "test.db")

    with Storage(db_path) as db:
        db.insert_session(_session_row("chat-1", raw_path))

    monkeypatch.setattr(processor, "summarize_chat", lambda chat_dict, api_key: VALID_SUMMARY)
    processor.process_batch(["chat-1"], api_key="fake-key", db_path=db_path)

    with Storage(db_path) as db:
        row = db.conn.execute(
            "SELECT searchable_text, keywords FROM search_index WHERE session_id = ?", ("chat-1",)
        ).fetchone()

    assert row is not None
    assert "Fixed a Minecraft mod crash" in row["searchable_text"]
    assert "minecraft" in row["keywords"]


def test_process_batch_rebuilds_fts5_index_after_batch(monkeypatch, tmp_path):
    """Regression test: keyword_search() prefers the FTS5 index over the
    LIKE fallback, but nothing ever built it after processing - so keyword
    and hybrid search silently used the slower/less-relevant LIKE path
    forever on a device that only ever ran collect+process."""
    raw_dir = tmp_path / "raw_chats"
    raw_dir.mkdir()
    raw_path = raw_dir / "chat-1.json"
    raw_path.write_text(json.dumps(SAMPLE_CHAT), encoding="utf-8")
    db_path = str(tmp_path / "test.db")

    with Storage(db_path) as db:
        db.insert_session(_session_row("chat-1", raw_path))

    monkeypatch.setattr(processor, "summarize_chat", lambda chat_dict, api_key: VALID_SUMMARY)
    processor.process_batch(["chat-1"], api_key="fake-key", db_path=db_path)

    with Storage(db_path) as db:
        results = db.search_fts5("minecraft")

    assert len(results) == 1
    assert results[0]["session_id"] == "chat-1"


def test_process_batch_embeds_into_chromadb(monkeypatch, tmp_path):
    """Regression test: process_batch() must call embed_session() so
    semantic search works immediately after processing, not only as a side
    effect of sync.py pulling data from another device (reindex_all())."""
    raw_dir = tmp_path / "raw_chats"
    raw_dir.mkdir()
    raw_path = raw_dir / "chat-1.json"
    raw_path.write_text(json.dumps(SAMPLE_CHAT), encoding="utf-8")
    db_path = str(tmp_path / "test.db")

    with Storage(db_path) as db:
        db.insert_session(_session_row("chat-1", raw_path))

    monkeypatch.setattr(processor, "summarize_chat", lambda chat_dict, api_key: VALID_SUMMARY)

    embed_calls = []
    monkeypatch.setattr(
        "src.embedder.embed_session",
        lambda session_id, summary_dict, chroma_path=None: embed_calls.append((session_id, summary_dict)) or True,
    )

    processor.process_batch(["chat-1"], api_key="fake-key", db_path=db_path)

    assert len(embed_calls) == 1
    embedded_id, embedded_summary = embed_calls[0]
    assert embedded_id == "chat-1"
    assert embedded_summary["source"] == "claude-ai"  # merged in from the session row
    assert embedded_summary["session_tldr"] == "Fixed a Minecraft mod crash."


def test_process_batch_indexing_failure_does_not_fail_the_session(monkeypatch, tmp_path):
    """Embedding/indexing is best-effort - a ChromaDB failure must not
    undo an already-persisted summary or mark a successfully-summarized
    session as failed."""
    raw_dir = tmp_path / "raw_chats"
    raw_dir.mkdir()
    raw_path = raw_dir / "chat-1.json"
    raw_path.write_text(json.dumps(SAMPLE_CHAT), encoding="utf-8")
    db_path = str(tmp_path / "test.db")

    with Storage(db_path) as db:
        db.insert_session(_session_row("chat-1", raw_path))

    monkeypatch.setattr(processor, "summarize_chat", lambda chat_dict, api_key: VALID_SUMMARY)
    monkeypatch.setattr(
        "src.embedder.embed_session",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("chroma is down")),
    )

    results = processor.process_batch(["chat-1"], api_key="fake-key", db_path=db_path)

    assert results["succeeded"] == ["chat-1"]
    with Storage(db_path) as db:
        assert db.get_session("chat-1")["status"] == "processed"
        assert db.get_summary("chat-1") is not None


def test_process_batch_persists_summary_and_marks_processed(monkeypatch, tmp_path):
    """Regression test: process_batch() must actually write to the summaries
    table and mark the session as processed, not just write a sidecar file.
    Previously it did neither, so a 'successful' process run left sessions
    permanently unsearchable (search.py reads from the summaries table)."""
    raw_dir = tmp_path / "raw_chats"
    raw_dir.mkdir()
    raw_path = raw_dir / "chat-1.json"
    raw_path.write_text(json.dumps(SAMPLE_CHAT), encoding="utf-8")
    db_path = str(tmp_path / "test.db")

    with Storage(db_path) as db:
        db.insert_session(_session_row("chat-1", raw_path))

    monkeypatch.setattr(processor, "summarize_chat", lambda chat_dict, api_key: VALID_SUMMARY)

    processor.process_batch(["chat-1"], api_key="fake-key", db_path=db_path)

    with Storage(db_path) as db:
        session = db.get_session("chat-1")
        summary = db.get_summary("chat-1")

    assert session["status"] == "processed"
    assert session["processed_at"] is not None
    assert summary is not None
    assert summary["tldr"] == "Fixed a Minecraft mod crash."
    assert summary["learnings"] == ["Check stack traces first"]


def test_process_batch_invalid_schema_marks_needs_review_in_db(monkeypatch, tmp_path):
    raw_dir = tmp_path / "raw_chats"
    raw_dir.mkdir()
    raw_path = raw_dir / "chat-1.json"
    raw_path.write_text(json.dumps(SAMPLE_CHAT), encoding="utf-8")
    db_path = str(tmp_path / "test.db")

    with Storage(db_path) as db:
        db.insert_session(_session_row("chat-1", raw_path))

    def raise_invalid(chat_dict, api_key):
        raise ValueError("bad schema")

    monkeypatch.setattr(processor, "summarize_chat", raise_invalid)

    results = processor.process_batch(["chat-1"], api_key="fake-key", db_path=db_path)

    assert "chat-1" in results["needs_review"]
    with Storage(db_path) as db:
        session = db.get_session("chat-1")
    assert session["status"] == "needs_review"
