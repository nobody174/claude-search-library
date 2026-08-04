import json
from unittest.mock import MagicMock

import pytest

from src import crypto, embedder, sync
from src.storage import Storage


@pytest.fixture(autouse=True)
def redirect_log(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "LOG_PATH", tmp_path / "sync.log")
    sync.logger.handlers.clear()
    monkeypatch.setattr(sync, "_device_id", lambda: "test-device")
    yield


@pytest.fixture(autouse=True)
def isolated_chroma(tmp_path, monkeypatch):
    """Prevent unmocked reindex_all() calls (triggered by real
    pull_from_github() runs in this file) from falling through to
    embedder.DEFAULT_CHROMA_PATH — the real, persistent user archive.

    SyncWorker defaults chroma_path=None, and reindex_all(chroma_path=None)
    resolves to DEFAULT_CHROMA_PATH; without this, any test that exercises
    pull_from_github()'s reindex step for real (rather than monkeypatching
    src.embedder.reindex_all) silently wipes and repopulates the user's
    actual ChromaDB collection with test fixture sessions.
    """
    monkeypatch.setattr(embedder, "_client", None)
    monkeypatch.setattr(embedder, "_collection", None)
    monkeypatch.setattr(embedder, "_client_path", None)
    monkeypatch.setattr(embedder, "DEFAULT_CHROMA_PATH", tmp_path / "chromadb")
    yield


@pytest.fixture
def repo_path(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    return path


@pytest.fixture
def encryption_key():
    return crypto.derive_encryption_key("test-passphrase", "JBSWY3DPEHPK3PXP")


@pytest.fixture
def mock_repo(monkeypatch):
    """Patch sync._open_repo to return a fully-mocked GitPython Repo."""
    repo = MagicMock()
    repo.index = MagicMock()
    repo.remote.return_value = MagicMock()
    monkeypatch.setattr(sync, "_open_repo", lambda path: repo)
    return repo


def _sample_session(session_id="sess-1", updated_at="2026-07-31T15:00:00+00:00"):
    return {
        "id": session_id, "source": "claude-ai", "device": "desktop",
        "title": "t", "created_at": "2026-07-31T14:00:00+00:00", "updated_at": updated_at,
        "duration_seconds": 0, "message_count": 2, "user_message_count": 1,
        "assistant_message_count": 1, "raw_file_path": None, "summary_file_path": None,
        "content_hash": f"hash-{session_id}", "processed_at": None, "status": "processed",
        "review_reason": None, "synced_at": None, "sync_version": 1,
    }


SAMPLE_SUMMARY = {
    "session_tldr": "Did a thing.",
    "learnings": ["learned something"],
    "patterns": ["a pattern"],
    "tags": ["tag1"],
    "mentioned_tools": [], "mentioned_languages": [], "mentioned_frameworks": [],
    "estimated_effort_minutes": 10, "topic_categories": [], "confidence_score": 0.8,
}


def test_push_file_writes_commits_and_pushes(repo_path, mock_repo, tmp_path):
    sync.push_file("secrets.enc", "encrypted-blob-content", repo_path=str(repo_path))

    written = repo_path / "secrets.enc"
    assert written.read_text(encoding="utf-8") == "encrypted-blob-content"
    mock_repo.index.add.assert_called_once()
    mock_repo.index.commit.assert_called_once()
    mock_repo.remote.assert_called_with(name="origin")


def test_fetch_file_pulls_and_reads(repo_path, mock_repo):
    (repo_path / "secrets.enc").write_text("stored-blob", encoding="utf-8")

    result = sync.fetch_file("secrets.enc", repo_path=str(repo_path))

    assert result == "stored-blob"
    mock_repo.remote.return_value.pull.assert_called_once()


def test_fetch_file_missing_raises(repo_path, mock_repo):
    with pytest.raises(FileNotFoundError):
        sync.fetch_file("nonexistent.enc", repo_path=str(repo_path))


def test_check_for_changes_no_prior_sync_counts_all(repo_path, mock_repo, tmp_path, encryption_key):
    db_path = str(tmp_path / "test.db")
    with Storage(db_path) as db:
        db.insert_session(_sample_session())

    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=db_path)
    assert worker.check_for_changes() == 1


def test_check_for_changes_respects_per_session_synced_at(repo_path, mock_repo, tmp_path, encryption_key):
    db_path = str(tmp_path / "test.db")
    with Storage(db_path) as db:
        db.insert_session(_sample_session(updated_at="2026-07-30T00:00:00+00:00"))
        db.update_session("sess-1", {"synced_at": "2026-07-31T00:00:00+00:00"})

    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=db_path)
    assert worker.check_for_changes() == 0


def test_check_for_changes_counts_old_content_never_synced(repo_path, mock_repo, tmp_path, encryption_key):
    """Regression test for a real bug (2026-08-04): a session whose
    *content* predates this device's sync history (e.g. a bulk historical
    import - a real conversation from months ago, imported today) must
    still count as needing a push. The old implementation compared each
    session's content timestamp against a single device-level "last
    push" wall-clock checkpoint, so any newly-imported old content was
    silently treated as already-synced forever, even though it had never
    actually been pushed. Reproduces the exact scenario: a device that
    has pushed before (so it has *some* synced sessions) imports a
    conversation dated long before that prior push."""
    db_path = str(tmp_path / "test.db")
    with Storage(db_path) as db:
        db.insert_session(_sample_session(session_id="already-synced", updated_at="2026-08-01T00:00:00+00:00"))
        db.update_session("already-synced", {"synced_at": "2026-08-02T00:00:00+00:00"})
        # Imported today, but its content is from months ago - never synced.
        db.insert_session(_sample_session(session_id="old-import", updated_at="2026-03-01T00:00:00+00:00"))

    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=db_path)
    assert worker.check_for_changes() == 1


def test_push_to_github_encrypts_and_commits(repo_path, mock_repo, tmp_path, encryption_key):
    db_path = str(tmp_path / "test.db")
    with Storage(db_path) as db:
        db.insert_session(_sample_session())
        db.store_summary("sess-1", SAMPLE_SUMMARY)

    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=db_path)
    result = worker.push_to_github()

    assert result["files_changed"] == 2  # session metadata + summary; no raw_file_path set
    session_path = repo_path / sync.ENCRYPTED_SESSIONS_DIR / "sess-1_session.enc"
    summary_path = repo_path / sync.ENCRYPTED_SUMMARIES_DIR / "sess-1_summary.enc"
    assert session_path.exists()
    assert summary_path.exists()

    # Verify both are actually encrypted (not plaintext JSON) and round-trip.
    session_ciphertext = session_path.read_text(encoding="utf-8")
    assert "Minecraft" not in session_ciphertext and "claude-ai" not in session_ciphertext
    decrypted_session = json.loads(crypto.decrypt_data(session_ciphertext, encryption_key))
    assert decrypted_session["id"] == "sess-1"
    assert decrypted_session["source"] == "claude-ai"
    # Local-only fields must not be pushed to another device.
    assert "raw_file_path" not in decrypted_session
    assert "summary_file_path" not in decrypted_session

    ciphertext = summary_path.read_text(encoding="utf-8")
    assert "session_tldr" not in ciphertext
    decrypted = json.loads(crypto.decrypt_data(ciphertext, encryption_key))
    assert decrypted["tldr"] == "Did a thing."

    mock_repo.remote.return_value.push.assert_called_once()


def test_push_to_github_skips_already_synced_sessions(repo_path, mock_repo, tmp_path, encryption_key):
    db_path = str(tmp_path / "test.db")
    with Storage(db_path) as db:
        db.insert_session(_sample_session(updated_at="2026-07-30T00:00:00+00:00"))
        db.update_session("sess-1", {"synced_at": "2026-07-31T00:00:00+00:00"})
        db.store_summary("sess-1", SAMPLE_SUMMARY)

    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=db_path)
    result = worker.push_to_github()

    assert result["files_changed"] == 0
    mock_repo.remote.return_value.push.assert_not_called()


def test_push_to_github_pushes_old_content_never_synced(repo_path, mock_repo, tmp_path, encryption_key):
    """Regression test for the real 2026-08-04 bug (see
    test_check_for_changes_counts_old_content_never_synced): a device
    that has already pushed before must still push a newly-imported
    session whose content predates that prior push."""
    db_path = str(tmp_path / "test.db")
    with Storage(db_path) as db:
        db.insert_session(_sample_session(session_id="already-synced", updated_at="2026-08-01T00:00:00+00:00"))
        db.update_session("already-synced", {"synced_at": "2026-08-02T00:00:00+00:00"})
        db.insert_session(_sample_session(session_id="old-import", updated_at="2026-03-01T00:00:00+00:00"))

    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=db_path)
    result = worker.push_to_github()

    assert result["files_changed"] == 1  # only old-import's session metadata (no summary set)
    assert (repo_path / sync.ENCRYPTED_SESSIONS_DIR / "old-import_session.enc").exists()
    assert not (repo_path / sync.ENCRYPTED_SESSIONS_DIR / "already-synced_session.enc").exists()

    with Storage(db_path) as db:
        pushed = db.get_session("old-import")
        assert pushed["synced_at"] is not None
        assert pushed["sync_version"] == 2  # bumped from the default 1


def test_pull_does_not_suppress_a_later_push(repo_path, mock_repo, tmp_path, encryption_key):
    """Regression test: pull_from_github() used to bump this device's
    last_sync_at to "now", and push_to_github() used that same field as
    its "only push sessions updated after this" checkpoint. Since a
    session's updated_at is always in the past relative to a pull that
    just happened, a pull immediately followed by a push — the ordinary
    "check for changes, then sync" flow — silently pushed nothing at
    all, even for a session that had never been pushed before.
    """
    db_path = str(tmp_path / "test.db")
    with Storage(db_path) as db:
        db.insert_session(_sample_session(updated_at="2026-07-31T15:00:00+00:00"))

    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=db_path)

    # A pull with nothing to pull still calls _update_device_metadata().
    worker.pull_from_github()

    # The never-before-pushed session must still go out.
    result = worker.push_to_github()
    assert result["files_changed"] > 0
    mock_repo.remote.return_value.push.assert_called_once()


def test_pull_from_github_decrypts_and_merges(repo_path, mock_repo, tmp_path, encryption_key):
    db_path = str(tmp_path / "test.db")
    summaries_dir = repo_path / sync.ENCRYPTED_SUMMARIES_DIR
    summaries_dir.mkdir(parents=True)

    with Storage(db_path) as db:
        db.insert_session(_sample_session("sess-remote"))

    remote_summary = dict(SAMPLE_SUMMARY, created_at="2026-07-31T16:00:00+00:00")
    blob = crypto.encrypt_data(json.dumps(remote_summary).encode("utf-8"), encryption_key)
    (summaries_dir / "sess-remote_summary.enc").write_text(blob, encoding="utf-8")

    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=db_path)
    result = worker.pull_from_github()

    assert result["files_changed"] == 1
    assert result["conflicts"] == 0
    mock_repo.remote.return_value.pull.assert_called_once()

    with Storage(db_path) as db:
        summary = db.get_summary("sess-remote")
        assert summary["tldr"] == "Did a thing."


def test_pull_from_github_fresh_device_with_no_local_sessions(repo_path, mock_repo, tmp_path, encryption_key):
    """Regression test: a second/fresh device that has never locally
    collected anything must still be able to pull. Previously
    pull_from_github() only ever decrypted *_summary.enc and called
    db.store_summary() directly - since summaries.session_id has a foreign
    key to sessions.id, this crashed with an IntegrityError on any device
    that didn't already have a matching session row, which is exactly the
    normal case for a second device joining an existing archive.
    """
    db_path = str(tmp_path / "test.db")
    sessions_dir = repo_path / sync.ENCRYPTED_SESSIONS_DIR
    summaries_dir = repo_path / sync.ENCRYPTED_SUMMARIES_DIR
    sessions_dir.mkdir(parents=True)
    summaries_dir.mkdir(parents=True)

    # No db.insert_session() call here - this device has never seen
    # "sess-remote" before. Both the session metadata and the summary
    # arrive only via the encrypted pull.
    remote_session = _sample_session("sess-remote")
    session_blob = crypto.encrypt_data(json.dumps(remote_session).encode("utf-8"), encryption_key)
    (sessions_dir / "sess-remote_session.enc").write_text(session_blob, encoding="utf-8")

    remote_summary = dict(SAMPLE_SUMMARY, created_at="2026-07-31T16:00:00+00:00")
    summary_blob = crypto.encrypt_data(json.dumps(remote_summary).encode("utf-8"), encryption_key)
    (summaries_dir / "sess-remote_summary.enc").write_text(summary_blob, encoding="utf-8")

    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=db_path)
    result = worker.pull_from_github()  # must not raise IntegrityError

    assert result["files_changed"] == 1
    assert result["conflicts"] == 0

    with Storage(db_path) as db:
        session = db.get_session("sess-remote")
        summary = db.get_summary("sess-remote")

    assert session is not None
    assert session["source"] == "claude-ai"
    assert summary["tldr"] == "Did a thing."


def test_pull_from_github_summary_without_matching_session_is_skipped(repo_path, mock_repo, tmp_path, encryption_key):
    """A summary with no corresponding *_session.enc (e.g. a partial or
    corrupted push) must be skipped gracefully, not crash the whole pull."""
    db_path = str(tmp_path / "test.db")
    summaries_dir = repo_path / sync.ENCRYPTED_SUMMARIES_DIR
    summaries_dir.mkdir(parents=True)

    orphan_summary = dict(SAMPLE_SUMMARY, created_at="2026-07-31T16:00:00+00:00")
    blob = crypto.encrypt_data(json.dumps(orphan_summary).encode("utf-8"), encryption_key)
    (summaries_dir / "sess-orphan_summary.enc").write_text(blob, encoding="utf-8")

    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=db_path)
    result = worker.pull_from_github()  # must not raise

    assert result["files_changed"] == 0
    assert result["conflicts"] == 1
    with Storage(db_path) as db:
        assert db.get_session("sess-orphan") is None


def test_pull_from_github_lww_conflict_keeps_newer_local(repo_path, mock_repo, tmp_path, encryption_key):
    db_path = str(tmp_path / "test.db")
    summaries_dir = repo_path / sync.ENCRYPTED_SUMMARIES_DIR
    summaries_dir.mkdir(parents=True)

    with Storage(db_path) as db:
        db.insert_session(_sample_session("sess-1", updated_at="2026-08-01T00:00:00+00:00"))
        newer_summary = dict(SAMPLE_SUMMARY, session_tldr="Newer local version")
        db.store_summary("sess-1", newer_summary)

    older_remote = dict(SAMPLE_SUMMARY, session_tldr="Older remote version", created_at="2026-07-01T00:00:00+00:00")
    blob = crypto.encrypt_data(json.dumps(older_remote).encode("utf-8"), encryption_key)
    (summaries_dir / "sess-1_summary.enc").write_text(blob, encoding="utf-8")

    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=db_path)
    result = worker.pull_from_github()

    assert result["conflicts"] == 1
    with Storage(db_path) as db:
        summary = db.get_summary("sess-1")
        assert summary["tldr"] == "Newer local version"


def test_pull_from_github_skips_undecryptable_files(repo_path, mock_repo, tmp_path, encryption_key):
    db_path = str(tmp_path / "test.db")
    summaries_dir = repo_path / sync.ENCRYPTED_SUMMARIES_DIR
    summaries_dir.mkdir(parents=True)
    (summaries_dir / "corrupt_summary.enc").write_text("not-valid-fernet-token", encoding="utf-8")

    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=db_path)
    result = worker.pull_from_github()

    assert result["files_changed"] == 0


def test_sync_bidirectional_calls_pull_and_push(repo_path, mock_repo, tmp_path, encryption_key, monkeypatch):
    db_path = str(tmp_path / "test.db")
    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=db_path)

    monkeypatch.setattr(worker, "pull_from_github", lambda: {"direction": "pull", "files_changed": 0, "conflicts": 0})
    monkeypatch.setattr(worker, "push_to_github", lambda: {"direction": "push", "files_changed": 0, "conflicts": 0})

    result = worker.sync(direction="bidirectional")
    assert result["pull"]["direction"] == "pull"
    assert result["push"]["direction"] == "push"


def test_sync_relays_reindexed_count_from_pull(repo_path, mock_repo, tmp_path, encryption_key, monkeypatch):
    """sync()'s reindexed count must come from whatever pull_from_github()
    reports — reindexing happens inside pull_from_github() itself (so it
    also fires for callers that call pull_from_github() directly, like
    `cli.py sync --pull`), not duplicated in sync()'s own wrapper logic."""
    db_path = str(tmp_path / "test.db")
    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=db_path)

    monkeypatch.setattr(
        worker, "pull_from_github",
        lambda: {"direction": "pull", "files_changed": 3, "conflicts": 0, "reindexed": 3},
    )
    monkeypatch.setattr(worker, "push_to_github", lambda: {"direction": "push", "files_changed": 0, "conflicts": 0})

    result = worker.sync(direction="bidirectional")
    assert result["reindexed"] == 3


def test_pull_from_github_reindexes_chromadb_and_fts5_when_files_change(
    repo_path, mock_repo, tmp_path, encryption_key, monkeypatch
):
    """Regression test: reindexing (ChromaDB + search_index/FTS5) must
    happen inside pull_from_github() itself. Previously it only lived in
    sync()'s wrapper logic, so `cli.py sync --pull` (which calls
    pull_from_github() directly) silently skipped it — a pulled session
    landed in the database but was never embedded or indexed, so search
    returned nothing on the receiving device even though the pull itself
    reported success. Found via a real --join-device + --pull run on an
    actual second machine.
    """
    db_path = str(tmp_path / "test.db")
    sessions_dir = repo_path / sync.ENCRYPTED_SESSIONS_DIR
    summaries_dir = repo_path / sync.ENCRYPTED_SUMMARIES_DIR
    sessions_dir.mkdir(parents=True)
    summaries_dir.mkdir(parents=True)

    remote_session = dict(_sample_session("sess-remote"), status="processed")
    session_blob = crypto.encrypt_data(json.dumps(remote_session).encode("utf-8"), encryption_key)
    (sessions_dir / "sess-remote_session.enc").write_text(session_blob, encoding="utf-8")

    remote_summary = dict(SAMPLE_SUMMARY, created_at="2026-07-31T16:00:00+00:00")
    summary_blob = crypto.encrypt_data(json.dumps(remote_summary).encode("utf-8"), encryption_key)
    (summaries_dir / "sess-remote_summary.enc").write_text(summary_blob, encoding="utf-8")

    reindex_calls = []
    monkeypatch.setattr("src.embedder.reindex_all", lambda **kw: reindex_calls.append(kw) or 1)

    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=db_path)
    result = worker.pull_from_github()  # called directly, like cli.py sync --pull does

    assert result["files_changed"] == 1
    assert result["reindexed"] == 1
    assert len(reindex_calls) == 1

    with Storage(db_path) as db:
        index_row = db.conn.execute(
            "SELECT searchable_text FROM search_index WHERE session_id = ?", ("sess-remote",)
        ).fetchone()
        fts5_results = db.search_fts5("thing")  # SAMPLE_SUMMARY's tldr is "Did a thing."

    assert index_row is not None
    assert any(r["session_id"] == "sess-remote" for r in fts5_results)


def test_pull_from_github_skips_reindex_when_nothing_changed(
    repo_path, mock_repo, tmp_path, encryption_key, monkeypatch
):
    db_path = str(tmp_path / "test.db")
    reindex_calls = []
    monkeypatch.setattr("src.embedder.reindex_all", lambda **kw: reindex_calls.append(kw) or 0)

    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=db_path)
    result = worker.pull_from_github()

    assert result["files_changed"] == 0
    assert result["reindexed"] == 0
    assert len(reindex_calls) == 0  # no point rebuilding indexes when nothing new arrived


def test_sync_propagates_errors(repo_path, mock_repo, tmp_path, encryption_key, monkeypatch):
    db_path = str(tmp_path / "test.db")
    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=db_path)

    def failing_pull():
        raise RuntimeError("network down")

    monkeypatch.setattr(worker, "pull_from_github", failing_pull)

    with pytest.raises(RuntimeError):
        worker.sync(direction="pull")


@pytest.fixture(autouse=True)
def stub_run_collection(monkeypatch):
    """daemon_loop() now collects before every iteration by default
    (see collect_first) - stub it out in tests that aren't specifically
    exercising that behavior so they don't hit the real local collectors."""
    import src.orchestration as orchestration_module

    monkeypatch.setattr(
        orchestration_module, "run_collection",
        lambda fail_fast=False, db_path=None: {"new": 0, "errors": 0, "total": 0, "sources": {}},
    )


def test_daemon_loop_syncs_when_changes_detected(repo_path, mock_repo, tmp_path, encryption_key, monkeypatch):
    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=str(tmp_path / "test.db"))

    monkeypatch.setattr(worker, "check_for_changes", lambda: 2)
    sync_calls = []
    monkeypatch.setattr(worker, "sync", lambda direction="bidirectional": sync_calls.append(direction))
    monkeypatch.setattr(sync.time, "sleep", lambda s: None)

    worker.daemon_loop(interval=0, iterations=1)
    assert sync_calls == ["bidirectional"]


def test_daemon_loop_pulls_only_when_no_changes(repo_path, mock_repo, tmp_path, encryption_key, monkeypatch):
    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=str(tmp_path / "test.db"))

    monkeypatch.setattr(worker, "check_for_changes", lambda: 0)
    pull_calls = []
    monkeypatch.setattr(worker, "pull_from_github", lambda: pull_calls.append(1))
    sync_calls = []
    monkeypatch.setattr(worker, "sync", lambda direction="bidirectional": sync_calls.append(direction))
    monkeypatch.setattr(sync.time, "sleep", lambda s: None)

    worker.daemon_loop(interval=0, iterations=1)
    assert pull_calls == [1]
    assert sync_calls == []


def test_daemon_loop_runs_multiple_iterations(repo_path, mock_repo, tmp_path, encryption_key, monkeypatch):
    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=str(tmp_path / "test.db"))

    monkeypatch.setattr(worker, "check_for_changes", lambda: 0)
    call_count = {"n": 0}
    monkeypatch.setattr(worker, "pull_from_github", lambda: call_count.__setitem__("n", call_count["n"] + 1))
    monkeypatch.setattr(sync.time, "sleep", lambda s: None)

    worker.daemon_loop(interval=0, iterations=3)
    assert call_count["n"] == 3


def test_daemon_loop_collects_before_each_iteration_by_default(repo_path, mock_repo, tmp_path, encryption_key, monkeypatch):
    import src.orchestration as orchestration_module

    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=str(tmp_path / "test.db"))

    collect_calls = []
    monkeypatch.setattr(
        orchestration_module, "run_collection",
        lambda fail_fast=False, db_path=None: collect_calls.append(1) or {"new": 0, "errors": 0, "total": 0, "sources": {}},
    )
    monkeypatch.setattr(worker, "check_for_changes", lambda: 0)
    monkeypatch.setattr(worker, "pull_from_github", lambda: None)
    monkeypatch.setattr(sync.time, "sleep", lambda s: None)

    worker.daemon_loop(interval=0, iterations=3)
    assert len(collect_calls) == 3


def test_daemon_loop_collect_first_false_skips_collection(repo_path, mock_repo, tmp_path, encryption_key, monkeypatch):
    import src.orchestration as orchestration_module

    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=str(tmp_path / "test.db"))

    collect_calls = []
    monkeypatch.setattr(
        orchestration_module, "run_collection",
        lambda fail_fast=False, db_path=None: collect_calls.append(1) or {"new": 0, "errors": 0, "total": 0, "sources": {}},
    )
    monkeypatch.setattr(worker, "check_for_changes", lambda: 0)
    monkeypatch.setattr(worker, "pull_from_github", lambda: None)
    monkeypatch.setattr(sync.time, "sleep", lambda s: None)

    worker.daemon_loop(interval=0, iterations=2, collect_first=False)
    assert len(collect_calls) == 0
