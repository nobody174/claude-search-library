import json
from pathlib import Path

import pytest

from src.storage import Storage, compute_session_hash


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


# ---- compute_session_hash / store_session_with_hash ------------------

def test_compute_session_hash_deterministic():
    session = {"messages": [{"role": "user", "content": "hi"}], "title": "t", "source": "claude-ai"}
    assert compute_session_hash(session) == compute_session_hash(dict(session))


def test_compute_session_hash_ignores_id_and_other_metadata():
    base = {"messages": [{"role": "user", "content": "hi"}], "title": "t", "source": "claude-ai"}
    with_id_a = dict(base, id="session-a", device="desktop")
    with_id_b = dict(base, id="session-b", device="laptop")
    assert compute_session_hash(with_id_a) == compute_session_hash(with_id_b)


def test_compute_session_hash_differs_on_content_change():
    session_a = {"messages": [{"role": "user", "content": "hi"}], "title": "t", "source": "claude-ai"}
    session_b = {"messages": [{"role": "user", "content": "different"}], "title": "t", "source": "claude-ai"}
    assert compute_session_hash(session_a) != compute_session_hash(session_b)


def test_compute_session_hash_ignores_source():
    """The hash must be a property of the raw export's content
    (messages/title) only. Including 'source' would mean the exact same
    raw export file hashes differently depending on which collector read
    it, or hashes differently when collect.py's normalized dict (which
    adds 'source') is compared against a raw re-read of the same file that
    has no 'source' key at all (verify_archive()'s hash check does exactly
    that re-read)."""
    with_source = {"messages": [{"role": "user", "content": "hi"}], "title": "t", "source": "claude-ai"}
    without_source = {"messages": [{"role": "user", "content": "hi"}], "title": "t"}
    assert compute_session_hash(with_source) == compute_session_hash(without_source)


def test_compute_session_hash_matches_raw_export_shape():
    """The exact shape a raw export file has on disk (messages with role,
    content, and timestamp; a title; no 'source' key) must hash identically
    whether read directly or passed through unchanged."""
    raw_export = {
        "id": "some-id",
        "title": "Debugging session",
        "created_at": "2026-01-01T00:00:00Z",
        "messages": [
            {"role": "user", "content": "hi", "timestamp": "2026-01-01T00:00:01Z"},
            {"role": "assistant", "content": "hello", "timestamp": "2026-01-01T00:00:02Z"},
        ],
    }
    assert compute_session_hash(raw_export) == compute_session_hash(dict(raw_export))


def test_store_session_with_hash_uses_hash_source_when_given(db):
    """store_session_with_hash(session_dict, hash_source=...) must hash
    hash_source, not session_dict — this is what lets collector.py store a
    normalized session while hashing the original raw file, so the stored
    hash matches what verify_archive() recomputes later."""
    session = dict(SAMPLE_SESSION, id="sess-hash-source")
    del session["content_hash"]

    raw_export = {"messages": [{"role": "user", "content": "raw content"}], "title": "raw title"}
    expected_hash = compute_session_hash(raw_export)

    result = db.store_session_with_hash(session, hash_source=raw_export)

    assert result["hash"] == expected_hash
    stored = db.get_session("sess-hash-source")
    assert stored["content_hash"] == expected_hash


def test_store_session_with_hash_inserts_new_session(db):
    session = dict(SAMPLE_SESSION, id="sess-hash-1")
    del session["content_hash"]  # let store_session_with_hash compute it

    result = db.store_session_with_hash(session)

    assert result["status"] == "inserted"
    assert result["id"] == "sess-hash-1"
    stored = db.get_session("sess-hash-1")
    assert stored["content_hash"] == result["hash"]


def test_store_session_with_hash_skips_duplicate_content(db):
    session_a = dict(SAMPLE_SESSION, id="sess-hash-a")
    del session_a["content_hash"]
    session_b = dict(SAMPLE_SESSION, id="sess-hash-b")  # same title/source/messages
    del session_b["content_hash"]

    first = db.store_session_with_hash(session_a)
    second = db.store_session_with_hash(session_b)

    assert first["status"] == "inserted"
    assert second["status"] == "skipped_duplicate"
    assert second["hash"] == first["hash"]
    # Only the first session should actually exist in the table.
    assert db.get_session("sess-hash-b") is None
    assert db.get_session_count() == 1


# ---- JSONL durability mirror ------------------------------------------

def test_export_summaries_to_jsonl_writes_all_summaries(db, tmp_path):
    db.insert_session(SAMPLE_SESSION)
    db.store_summary("sess-1", SAMPLE_SUMMARY)
    second_session = dict(SAMPLE_SESSION, id="sess-2", content_hash="def456")
    db.insert_session(second_session)
    db.store_summary("sess-2", dict(SAMPLE_SUMMARY, session_tldr="Second summary"))

    output_file = str(tmp_path / "summaries" / "mirror.jsonl")
    count = db.export_summaries_to_jsonl(output_file)

    assert count == 2
    lines = [json.loads(l) for l in open(output_file, encoding="utf-8") if l.strip()]
    assert {l["session_id"] for l in lines} == {"sess-1", "sess-2"}


def test_export_summaries_to_jsonl_creates_parent_dirs(db, tmp_path):
    db.insert_session(SAMPLE_SESSION)
    db.store_summary("sess-1", SAMPLE_SUMMARY)

    output_file = str(tmp_path / "nested" / "dir" / "mirror.jsonl")
    db.export_summaries_to_jsonl(output_file)

    assert (tmp_path / "nested" / "dir" / "mirror.jsonl").exists()


def test_restore_summaries_from_jsonl_missing_file_raises(db, tmp_path):
    with pytest.raises(FileNotFoundError):
        db.restore_summaries_from_jsonl(str(tmp_path / "does-not-exist.jsonl"))


def test_restore_summaries_from_jsonl_round_trip(tmp_path):
    output_file = str(tmp_path / "mirror.jsonl")

    with Storage(":memory:") as source_db:
        source_db.insert_session(SAMPLE_SESSION)
        source_db.store_summary("sess-1", SAMPLE_SUMMARY)
        exported = source_db.export_summaries_to_jsonl(output_file)
    assert exported == 1

    # Restoring into a fresh database (with the referenced session already
    # present, since summaries has a foreign key to sessions) should
    # reproduce the summary row.
    with Storage(":memory:") as target_db:
        target_db.insert_session(SAMPLE_SESSION)
        restored_count = target_db.restore_summaries_from_jsonl(output_file)
        summary = target_db.get_summary("sess-1")

    assert restored_count == 1
    assert summary["tldr"] == "Fixed the mod crash."
    assert summary["learnings"] == ["Check stack traces"]


def test_restore_summaries_from_jsonl_is_idempotent(tmp_path):
    output_file = str(tmp_path / "mirror.jsonl")

    with Storage(":memory:") as source_db:
        source_db.insert_session(SAMPLE_SESSION)
        source_db.store_summary("sess-1", SAMPLE_SUMMARY)
        source_db.export_summaries_to_jsonl(output_file)

    with Storage(":memory:") as target_db:
        target_db.insert_session(SAMPLE_SESSION)
        target_db.restore_summaries_from_jsonl(output_file)
        first_count = target_db.conn.execute("SELECT COUNT(*) FROM summaries").fetchone()[0]
        target_db.restore_summaries_from_jsonl(output_file)
        second_count = target_db.conn.execute("SELECT COUNT(*) FROM summaries").fetchone()[0]

    assert first_count == 1
    assert second_count == 1


# ---- verify_archive -----------------------------------------------------

def _session_with_raw_file(session_id, raw_path, content_hash=None, session_content=None):
    content = session_content or {"id": session_id, "title": "t", "source": "claude-ai", "messages": []}
    Path(raw_path).write_text(json.dumps(content), encoding="utf-8")
    return dict(
        SAMPLE_SESSION,
        id=session_id,
        raw_file_path=str(raw_path),
        content_hash=content_hash or compute_session_hash(content),
    )


def test_verify_archive_empty_db_is_healthy(db):
    result = db.verify_archive(verbose=False)

    assert result["healthy"] is True
    assert result["checks_failed"] == 0
    assert result["checks_passed"] == 7
    assert result["errors"] == []
    assert "stats" in result
    assert "timestamp" in result


def test_verify_archive_returns_expected_stats_keys(db):
    result = db.verify_archive()

    stats = result["stats"]
    assert "total_sessions" in stats
    assert "total_summaries" in stats
    assert "total_search_index_rows" in stats
    assert stats["total_sessions"] >= 0


def test_verify_archive_warns_on_missing_jsonl_but_still_passes(tmp_path):
    # Must be a real db_path, not ":memory:" - the JSONL mirror path is
    # derived from db_path's directory, and ":memory:" has none, so that
    # case is a distinct "not applicable" branch (see the test below).
    # tmp_path keeps this isolated from any real ~/.claude-search-library
    # mirror file that might already exist on the machine running the test.
    db_path = str(tmp_path / "data" / "claude_search.db")
    with Storage(db_path) as db:
        result = db.verify_archive()

    # JSONL won't exist until export_summaries_to_jsonl() is called - this
    # should be a warning, not an error, and the check should still pass.
    assert any("JSONL mirror not found" in w for w in result["warnings"])
    assert result["healthy"] is True
    assert result["checks_passed"] > 0


def test_verify_archive_skips_jsonl_check_for_in_memory_db(db):
    result = db.verify_archive()

    assert any("no on-disk mirror location" in w for w in result["warnings"])
    assert result["healthy"] is True


def test_verify_archive_warns_on_missing_fts5_index(db):
    result = db.verify_archive()
    assert any("FTS5 index not yet created" in w for w in result["warnings"])
    assert result["stats"]["fts5_index_exists"] is False


def test_verify_archive_no_warning_once_fts5_index_exists(db):
    db.create_fts5_index()
    result = db.verify_archive()
    assert result["stats"]["fts5_index_exists"] is True
    assert not any("FTS5 index not yet created" in w for w in result["warnings"])


def test_verify_archive_detects_session_summary_count_mismatch(db):
    db.insert_session(SAMPLE_SESSION)
    # No matching summary inserted - counts should now differ.
    result = db.verify_archive()
    assert any("Session/summary mismatch" in w for w in result["warnings"])
    assert result["healthy"] is True  # mismatch is a warning, not an error


def test_verify_archive_detects_real_content_hash_mismatch(db, tmp_path):
    raw_path = tmp_path / "sess-hash.json"
    session = _session_with_raw_file("sess-hash", raw_path)
    session["content_hash"] = "deliberately-wrong-hash"
    db.insert_session(session)

    result = db.verify_archive()

    assert result["healthy"] is False
    assert any("content hash mismatch" in e for e in result["errors"])
    assert result["stats"]["hash_samples_checked"] == 1
    assert result["stats"]["hash_samples_valid"] == 0


def test_verify_archive_passes_when_hash_matches_raw_file(db, tmp_path):
    raw_path = tmp_path / "sess-ok.json"
    session = _session_with_raw_file("sess-ok", raw_path)
    db.insert_session(session)

    result = db.verify_archive()

    assert result["healthy"] is True
    assert result["stats"]["hash_samples_checked"] == 1
    assert result["stats"]["hash_samples_valid"] == 1


def test_verify_archive_warns_when_raw_file_missing_for_hash_check(db):
    # Must be under Path.home() - verify_archive() treats a path outside
    # the current device's home dir as another device's synced session
    # (not a local file that's genuinely missing) and skips it entirely.
    missing_local_path = str(Path.home() / ".claude-search-library" / "does-not-exist.json")
    session = dict(SAMPLE_SESSION, id="sess-no-raw", raw_file_path=missing_local_path)
    db.insert_session(session)

    result = db.verify_archive()

    assert any("no readable raw file" in w for w in result["warnings"])
    assert result["stats"]["hash_samples_checked"] == 0


def test_verify_archive_flags_missing_raw_chat_file(db):
    missing_local_path = str(Path.home() / ".claude-search-library" / "does-not-exist.json")
    session = dict(SAMPLE_SESSION, id="sess-missing-file", raw_file_path=missing_local_path)
    db.insert_session(session)

    result = db.verify_archive()

    assert result["stats"]["raw_chat_files_missing"] == 1
    assert any("no longer exists" in w for w in result["warnings"])


def test_verify_archive_skips_other_devices_raw_paths(db):
    """A path outside this device's home dir is a synced session from
    another device, not a local file gone missing - should not be counted
    or warned about at all."""
    foreign_path = "/completely/different/machine/raw_exports/claude-code/abc.json"
    session = dict(SAMPLE_SESSION, id="sess-foreign-device", raw_file_path=foreign_path)
    db.insert_session(session)

    result = db.verify_archive()

    assert result["stats"]["raw_chat_files_missing"] == 0
    assert result["stats"]["sessions_with_raw_path"] == 0
    assert not any("no longer exists" in w for w in result["warnings"])
    assert not any("no readable raw file" in w for w in result["warnings"])


def test_verify_archive_treats_null_raw_path_on_synced_session_as_foreign_device(db):
    """A NULL raw_file_path on a session that HAS been synced (synced_at
    set) is the same foreign-device story as an explicit foreign path -
    e.g. a Claude Code session collected on another device, whose
    locally-converted transcript file never existed here. Traced from 5
    real sessions in production data (see BACKLOG.md/CHANGELOG.md
    2026-08-06) - must not be counted as a genuine "missing raw file"."""
    session = dict(
        SAMPLE_SESSION, id="sess-synced-no-raw",
        raw_file_path=None, synced_at="2026-08-04T03:41:13+00:00",
    )
    db.insert_session(session)

    result = db.verify_archive()

    assert result["stats"]["raw_chat_files_missing"] == 0
    assert not any("no readable raw file" in w for w in result["warnings"])


def test_verify_archive_treats_null_raw_path_on_unsynced_session_as_genuinely_missing(db):
    """A NULL raw_file_path on a session that has NEVER been synced
    (synced_at is None) is a genuine local anomaly, distinct from the
    foreign-device case above - this session originated on THIS device
    and should have had a raw file recorded."""
    session = dict(
        SAMPLE_SESSION, id="sess-local-no-raw",
        raw_file_path=None, synced_at=None,
    )
    db.insert_session(session)

    result = db.verify_archive()

    assert any("no readable raw file" in w for w in result["warnings"])


def test_verify_archive_flags_missing_summary_sidecar_file(db):
    """summary_file_path is the same device-local-path-in-synced-data
    pattern as raw_file_path - same check, same home-dir-scoping."""
    missing_local_path = str(Path.home() / ".claude-search-library" / "summaries" / "does-not-exist.json")
    session = dict(SAMPLE_SESSION, id="sess-missing-summary", summary_file_path=missing_local_path)
    db.insert_session(session)

    result = db.verify_archive()

    assert result["stats"]["summary_sidecar_files_missing"] == 1
    assert any("summary sidecar file that no longer exists" in w for w in result["warnings"])


def test_verify_archive_skips_other_devices_summary_paths(db):
    foreign_path = "/completely/different/machine/summaries/abc.json"
    session = dict(SAMPLE_SESSION, id="sess-foreign-summary", summary_file_path=foreign_path)
    db.insert_session(session)

    result = db.verify_archive()

    assert result["stats"]["summary_sidecar_files_missing"] == 0
    assert result["stats"]["sessions_with_summary_path"] == 0
    assert not any("summary sidecar file that no longer exists" in w for w in result["warnings"])


def test_verify_archive_reads_valid_jsonl_mirror(tmp_path):
    db_path = str(tmp_path / "data" / "claude_search.db")
    with Storage(db_path) as db:
        db.insert_session(SAMPLE_SESSION)
        db.store_summary("sess-1", SAMPLE_SUMMARY)
        db.export_summaries_to_jsonl()  # writes to the db_path-derived default location

        result = db.verify_archive()

    assert result["stats"]["jsonl_lines"] == 1
    assert not any("JSONL mirror not found" in w for w in result["warnings"])


def test_verify_archive_flags_invalid_jsonl_line(tmp_path):
    db_path = str(tmp_path / "data" / "claude_search.db")
    with Storage(db_path) as db:
        jsonl_path = Path(db._default_jsonl_path())
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        jsonl_path.write_text('{"session_id": "s1"}\nnot valid json\n', encoding="utf-8")

        result = db.verify_archive()

    assert result["healthy"] is False
    assert any("Invalid JSON in JSONL mirror" in e for e in result["errors"])


def test_verify_archive_warns_on_device_with_no_name(db):
    db.conn.execute(
        "INSERT INTO sync_metadata (device_id, device_name, pending_changes) VALUES (?, NULL, 0)",
        ("unnamed-device",),
    )
    db.conn.commit()

    result = db.verify_archive()

    assert result["stats"]["devices_registered"] == 1
    assert any("has no device_name set" in w for w in result["warnings"])


def test_verify_archive_detects_database_corruption(tmp_path):
    db_path = tmp_path / "corrupt.db"
    # Write garbage bytes so this isn't a valid SQLite file at all.
    db_path.write_bytes(b"this is not a sqlite database" * 100)

    with pytest.raises(Exception):
        with Storage(str(db_path)) as db:
            db.verify_archive()


def test_opening_a_newer_schema_database_raises(tmp_path):
    """If this code's SCHEMA_VERSION is behind the database's own recorded
    version, opening it must fail loudly (SchemaTooNewError) instead of
    silently running old-shape queries against a newer schema - see
    _run_schema_upgrades's docstring for the real scenario this guards
    against (a second device, not yet git-pulled, opening a database
    another device already migrated further)."""
    from src.storage import SchemaTooNewError, SCHEMA_VERSION

    db_path = str(tmp_path / "future.db")
    with Storage(db_path):
        pass  # creates the DB at the current real SCHEMA_VERSION

    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE schema_meta SET value = ? WHERE key = 'version'",
        (str(SCHEMA_VERSION + 1),),
    )
    conn.commit()
    conn.close()

    with pytest.raises(SchemaTooNewError):
        with Storage(db_path):
            pass


def test_storage_with_no_explicit_path_honors_configured_db_path(tmp_path, monkeypatch):
    """Regression test for a real bug QA found (2026-08-06): every
    Storage() call in cli.py/server.py passed no db_path, so all of them
    silently used the hardcoded DEFAULT_DB_PATH instead of whatever
    config.yaml's storage.db_path actually declared - meaning
    config.yaml's db_path was only ever honored by the --init CLI path,
    not by day-to-day use. Storage() must now resolve a config.yaml in
    cwd (if present) before falling back to DEFAULT_DB_PATH."""
    configured_path = tmp_path / "configured" / "my_library.db"
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text(
        f"storage:\n  db_path: {configured_path.as_posix()}\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)

    with Storage() as db:
        assert db.db_path == str(configured_path)


def test_storage_with_no_explicit_path_falls_back_when_no_config_yaml(tmp_path, monkeypatch):
    """No config.yaml anywhere findable -> falls back to DEFAULT_DB_PATH
    (here, the test-monkeypatched one) exactly as before this fix."""
    import src.storage as storage_module

    monkeypatch.chdir(tmp_path)  # no config.yaml in this empty tmp_path
    fallback_path = tmp_path / "fallback.db"
    monkeypatch.setattr(storage_module, "DEFAULT_DB_PATH", fallback_path)

    with Storage() as db:
        assert db.db_path == str(fallback_path)
