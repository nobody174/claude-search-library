import json
from unittest.mock import MagicMock

import pytest

from src import crypto, sync
from src.storage import Storage


@pytest.fixture(autouse=True)
def redirect_log(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "LOG_PATH", tmp_path / "sync.log")
    sync.logger.handlers.clear()
    monkeypatch.setattr(sync, "_device_id", lambda: "test-device")
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


def test_check_for_changes_respects_last_sync(repo_path, mock_repo, tmp_path, encryption_key):
    db_path = str(tmp_path / "test.db")
    with Storage(db_path) as db:
        db.insert_session(_sample_session(updated_at="2026-07-30T00:00:00+00:00"))

    metadata = {
        "devices": {
            "test-device": {"last_sync_at": "2026-07-31T00:00:00+00:00", "pending_changes": 0}
        }
    }
    (repo_path / sync.SYNC_METADATA_FILENAME).write_text(json.dumps(metadata), encoding="utf-8")

    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=db_path)
    assert worker.check_for_changes() == 0


def test_push_to_github_encrypts_and_commits(repo_path, mock_repo, tmp_path, encryption_key):
    db_path = str(tmp_path / "test.db")
    with Storage(db_path) as db:
        db.insert_session(_sample_session())
        db.store_summary("sess-1", SAMPLE_SUMMARY)

    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=db_path)
    result = worker.push_to_github()

    assert result["files_changed"] == 1  # summary only, no raw_file_path set
    summary_path = repo_path / sync.ENCRYPTED_SUMMARIES_DIR / "sess-1_summary.enc"
    assert summary_path.exists()

    # Verify it's actually encrypted (not plaintext JSON) and round-trips.
    ciphertext = summary_path.read_text(encoding="utf-8")
    assert "session_tldr" not in ciphertext
    decrypted = json.loads(crypto.decrypt_data(ciphertext, encryption_key))
    assert decrypted["tldr"] == "Did a thing."

    mock_repo.remote.return_value.push.assert_called_once()


def test_push_to_github_skips_already_synced_sessions(repo_path, mock_repo, tmp_path, encryption_key):
    db_path = str(tmp_path / "test.db")
    with Storage(db_path) as db:
        db.insert_session(_sample_session(updated_at="2026-07-30T00:00:00+00:00"))
        db.store_summary("sess-1", SAMPLE_SUMMARY)

    metadata = {
        "devices": {"test-device": {"last_sync_at": "2026-07-31T00:00:00+00:00", "pending_changes": 0}}
    }
    (repo_path / sync.SYNC_METADATA_FILENAME).write_text(json.dumps(metadata), encoding="utf-8")

    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=db_path)
    result = worker.push_to_github()

    assert result["files_changed"] == 0
    mock_repo.remote.return_value.push.assert_not_called()


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


def test_sync_reindexes_when_pull_has_changes(repo_path, mock_repo, tmp_path, encryption_key, monkeypatch):
    db_path = str(tmp_path / "test.db")
    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=db_path)

    monkeypatch.setattr(worker, "pull_from_github", lambda: {"direction": "pull", "files_changed": 3, "conflicts": 0})
    monkeypatch.setattr(worker, "push_to_github", lambda: {"direction": "push", "files_changed": 0, "conflicts": 0})

    reindex_calls = []
    monkeypatch.setattr("src.embedder.reindex_all", lambda **kw: reindex_calls.append(kw) or 3)

    result = worker.sync(direction="bidirectional")
    assert result["reindexed"] == 3
    assert len(reindex_calls) == 1


def test_sync_propagates_errors(repo_path, mock_repo, tmp_path, encryption_key, monkeypatch):
    db_path = str(tmp_path / "test.db")
    worker = sync.SyncWorker(encryption_key, repo_path=str(repo_path), db_path=db_path)

    def failing_pull():
        raise RuntimeError("network down")

    monkeypatch.setattr(worker, "pull_from_github", failing_pull)

    with pytest.raises(RuntimeError):
        worker.sync(direction="pull")


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
