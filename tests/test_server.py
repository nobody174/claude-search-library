import json

import pytest

import server
from src.storage import Storage


def _session(session_id, source="claude-ai", status="processed", raw_file_path=None):
    return {
        "id": session_id, "source": source, "device": "desktop",
        "title": f"Title for {session_id}", "created_at": "2026-07-31T14:00:00+00:00", "updated_at": None,
        "duration_seconds": 0, "message_count": 2, "user_message_count": 1,
        "assistant_message_count": 1, "raw_file_path": raw_file_path, "summary_file_path": None,
        "content_hash": f"hash-{session_id}", "processed_at": None, "status": status,
        "review_reason": None, "synced_at": None, "sync_version": 1,
    }


@pytest.fixture
def client(tmp_path, monkeypatch):
    import src.storage as storage_module
    monkeypatch.setattr(storage_module, "DEFAULT_DB_PATH", tmp_path / "test.db")

    # /sync now collects from every local source first by default (see
    # server.py's /sync docstring) - stub it out so tests don't hit the
    # real local collectors (notably the slow claude-desktop one).
    # Individual tests that want to assert on this behavior override it.
    import src.orchestration as orchestration_module
    monkeypatch.setattr(
        orchestration_module, "run_collection",
        lambda fail_fast=False: {"new": 0, "errors": 0, "total": 0, "sources": {}},
    )

    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        # Every route except /setup and the static/index routes now
        # requires a valid session cookie (see server.py's before_request
        # session gate) - manufacture one directly rather than going
        # through a real /setup call, which needs real GitHub-hosted
        # encrypted TOTP secrets that don't exist in a test environment.
        token = server._create_session()
        c.set_cookie(server.SESSION_COOKIE_NAME, token)
        yield c


@pytest.fixture
def unauth_client(tmp_path, monkeypatch):
    """Same setup as `client`, but with no session cookie - for asserting
    the security gate itself actually rejects unauthenticated requests."""
    import src.storage as storage_module
    monkeypatch.setattr(storage_module, "DEFAULT_DB_PATH", tmp_path / "test.db")
    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        yield c


def test_protected_routes_reject_without_a_session(unauth_client):
    """Regression test for a real finding from a full security review: every
    route except /setup and the static/index routes used to be reachable
    with zero credentials at all - confirmed live via a bare curl call
    that returned real search results and cost data with no auth
    whatsoever. The web UI's "Unlock Device" screen was purely
    client-side (a localStorage flag), never enforced server-side."""
    assert unauth_client.get("/search?q=test").status_code == 401
    assert unauth_client.get("/costs").status_code == 401
    assert unauth_client.get("/stats").status_code == 401
    assert unauth_client.get("/health").status_code == 401
    assert unauth_client.get("/devices").status_code == 401
    assert unauth_client.post("/review/reprocess", json={}).status_code == 401


def test_public_routes_work_without_a_session(unauth_client):
    """/, /src/*, and /setup itself must stay reachable pre-unlock - that's
    the page/script that render the Unlock Device screen, and the
    endpoint that actually performs the unlock."""
    assert unauth_client.get("/").status_code == 200
    assert unauth_client.get("/src/api.js").status_code == 200
    # /setup reaches its own handler (which then 401s on bad credentials,
    # not because the session gate blocked it before the handler ran).
    resp = unauth_client.post("/setup", json={"passphrase": "x", "totp_code": "000000"})
    assert resp.status_code in (400, 401)
    assert resp.get_json().get("error") != "unlock required"


def test_setup_success_issues_a_session_cookie(unauth_client, monkeypatch):
    monkeypatch.setattr(server.crypto, "_fetch_secrets_from_github", lambda: "encrypted-blob")
    monkeypatch.setattr(server.crypto, "_derive_passphrase_only_key", lambda p: b"key")
    monkeypatch.setattr(server.crypto, "decrypt_data", lambda blob, key: b"totp-secret")
    monkeypatch.setattr(server.crypto, "verify_totp_code", lambda secret, code: True)

    resp = unauth_client.post("/setup", json={"passphrase": "correct", "totp_code": "123456"})
    assert resp.status_code == 200
    assert unauth_client.get_cookie(server.SESSION_COOKIE_NAME) is not None

    # The session just issued now grants access to a previously-401'd route.
    assert unauth_client.get("/stats").status_code == 200


def test_setup_locks_out_after_repeated_failures(unauth_client, monkeypatch):
    """Regression test for a real Devil's Advocate finding: /setup had no
    limit on how many passphrase+TOTP guesses could be thrown at it -
    Argon2id makes each guess expensive, but that's not the same as a
    bounded total attempt count."""
    monkeypatch.setattr(server, "_setup_attempts", {})
    monkeypatch.setattr(server.crypto, "_fetch_secrets_from_github", lambda: (_ for _ in ()).throw(Exception("nope")))

    for _ in range(server.SETUP_MAX_ATTEMPTS):
        resp = unauth_client.post("/setup", json={"passphrase": "wrong", "totp_code": "000000"})
        assert resp.status_code == 401

    resp = unauth_client.post("/setup", json={"passphrase": "wrong", "totp_code": "000000"})
    assert resp.status_code == 429
    assert "Too many failed attempts" in resp.get_json()["error"]


def test_setup_success_clears_prior_failures(unauth_client, monkeypatch):
    monkeypatch.setattr(server, "_setup_attempts", {})
    monkeypatch.setattr(server.crypto, "_fetch_secrets_from_github", lambda: "encrypted-blob")
    monkeypatch.setattr(server.crypto, "_derive_passphrase_only_key", lambda p: b"key")
    monkeypatch.setattr(server.crypto, "decrypt_data", lambda blob, key: b"totp-secret")

    monkeypatch.setattr(server.crypto, "verify_totp_code", lambda secret, code: False)
    for _ in range(server.SETUP_MAX_ATTEMPTS - 1):
        assert unauth_client.post("/setup", json={"passphrase": "x", "totp_code": "0"}).status_code == 401

    monkeypatch.setattr(server.crypto, "verify_totp_code", lambda secret, code: True)
    assert unauth_client.post("/setup", json={"passphrase": "x", "totp_code": "0"}).status_code == 200

    # A successful login clears the failure count, so a fresh round of
    # wrong attempts afterward isn't instantly locked out by leftover
    # history from before the successful login.
    monkeypatch.setattr(server.crypto, "verify_totp_code", lambda secret, code: False)
    assert unauth_client.post("/setup", json={"passphrase": "x", "totp_code": "0"}).status_code == 401


def test_logout_invalidates_the_session(client):
    assert client.get("/stats").status_code == 200
    resp = client.post("/logout")
    assert resp.status_code == 200
    assert client.get("/stats").status_code == 401


def test_expired_session_is_rejected(client, monkeypatch):
    # Simulate the session's TTL having already elapsed.
    for token in list(server._sessions):
        server._sessions[token] = 0
    assert client.get("/stats").status_code == 401


def test_index_page_serves_web_ui(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Claude Search Library" in resp.data


def test_src_assets_serves_api_js(client):
    resp = client.get("/src/api.js")
    assert resp.status_code == 200
    assert b"ClaudeSearchAPI" in resp.data


def test_search_endpoint_missing_query_returns_400(client):
    resp = client.get("/search")
    assert resp.status_code == 400


def test_search_endpoint_returns_results(client, monkeypatch):
    monkeypatch.setattr(
        "server.run_search",
        lambda query, mode="semantic", top_k=10, filters=None: [
            {"session_id": "s1", "title": "t", "tldr": "tldr", "relevance_score": 0.9}
        ],
    )

    resp = client.get("/search?q=minecraft&top_k=5")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_results"] == 1
    assert data["results"][0]["session_id"] == "s1"
    assert "query_time_ms" in data


def test_search_endpoint_defaults_to_hybrid_mode(client, monkeypatch):
    captured = {}

    def fake_search(query, mode="semantic", top_k=10, filters=None):
        captured["mode"] = mode
        return []

    monkeypatch.setattr("server.run_search", fake_search)

    resp = client.get("/search?q=minecraft")
    assert resp.status_code == 200
    assert captured["mode"] == "hybrid"
    assert resp.get_json()["mode"] == "hybrid"


def test_search_endpoint_accepts_explicit_mode(client, monkeypatch):
    captured = {}

    def fake_search(query, mode="semantic", top_k=10, filters=None):
        captured["mode"] = mode
        return []

    monkeypatch.setattr("server.run_search", fake_search)

    resp = client.get("/search?q=minecraft&mode=keyword")
    assert resp.status_code == 200
    assert captured["mode"] == "keyword"
    assert resp.get_json()["mode"] == "keyword"
    assert resp.get_json()["query"] == "minecraft"


def test_search_endpoint_passes_filters_through(client, monkeypatch):
    captured = {}

    def fake_search(query, mode="semantic", top_k=10, filters=None):
        captured["filters"] = filters
        return []

    monkeypatch.setattr("server.run_search", fake_search)

    resp = client.get(
        "/search?q=minecraft&" + "filters=" + json.dumps({"source": "claude-code", "tags": ["debugging"]})
    )
    assert resp.status_code == 200
    assert captured["filters"] == {"source": "claude-code", "tags": ["debugging"]}


def test_search_endpoint_no_filters_param_passes_none(client, monkeypatch):
    captured = {}

    def fake_search(query, mode="semantic", top_k=10, filters=None):
        captured["filters"] = filters
        return []

    monkeypatch.setattr("server.run_search", fake_search)

    resp = client.get("/search?q=minecraft")
    assert resp.status_code == 200
    assert captured["filters"] is None


def test_search_endpoint_rejects_invalid_filters_json(client):
    resp = client.get("/search?q=minecraft&filters=not-json")
    assert resp.status_code == 400


def test_session_endpoint_found(client):
    with Storage() as db:
        db.insert_session(_session("s1", raw_file_path="/raw/s1.json"))

    resp = client.get("/session/s1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["id"] == "s1"
    assert data["link_to_raw"] == "file:///raw/s1.json"


def test_session_endpoint_not_found(client):
    resp = client.get("/session/does-not-exist")
    assert resp.status_code == 404


def test_stats_endpoint(client):
    with Storage() as db:
        db.insert_session(_session("s1", source="claude-ai"))
        db.insert_session(_session("s2", source="vscode", status="needs_review"))

    resp = client.get("/stats")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_sessions"] == 2
    assert data["by_source"]["claude-ai"] == 1
    assert data["by_status"]["needs_review"] == 1
    assert "last_sync" in data


def test_health_endpoint_healthy_returns_200(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["healthy"] is True
    assert "stats" in data


def test_health_endpoint_unhealthy_returns_503(client, monkeypatch):
    monkeypatch.setattr(
        "src.storage.Storage.verify_archive",
        lambda self, verbose=False: {
            "healthy": False, "checks_passed": 6, "checks_failed": 1,
            "errors": ["Database integrity check failed: corrupted"], "warnings": [],
            "stats": {}, "timestamp": "2026-01-01T00:00:00Z",
        },
    )

    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.get_json()["healthy"] is False


def test_health_endpoint_exception_returns_500(client, monkeypatch):
    def boom(self, verbose=False):
        raise RuntimeError("db is on fire")

    monkeypatch.setattr("src.storage.Storage.verify_archive", boom)

    resp = client.get("/health")
    assert resp.status_code == 500
    assert resp.get_json()["healthy"] is False


def test_devices_endpoint(client):
    with Storage() as db:
        db.conn.execute(
            "INSERT INTO sync_metadata (device_id, device_name, last_sync_at, pending_changes) "
            "VALUES ('dev1', 'Desktop', '2026-07-31T14:00:00Z', 0)"
        )
        db.conn.commit()

    resp = client.get("/devices")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["devices"]) == 1
    assert data["devices"][0]["device_name"] == "Desktop"


def test_devices_endpoint_empty(client):
    resp = client.get("/devices")
    assert resp.status_code == 200
    assert resp.get_json()["devices"] == []


def test_approve_review_endpoint(client):
    with Storage() as db:
        db.insert_session(_session("s1", status="needs_review"))

    resp = client.post(
        "/review/s1/approve",
        data=json.dumps({"approved": True, "notes": "looks fine"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["approved"] is True

    with Storage() as db:
        session = db.get_session("s1")
        assert session["status"] == "processed"
        assert session["review_reason"] == "looks fine"


def test_approve_review_endpoint_not_found(client):
    resp = client.post(
        "/review/does-not-exist/approve",
        data=json.dumps({"approved": True}),
        content_type="application/json",
    )
    assert resp.status_code == 404


def test_approve_review_endpoint_rejects_without_marking_processed(client):
    with Storage() as db:
        db.insert_session(_session("s1", status="needs_review"))

    resp = client.post(
        "/review/s1/approve",
        data=json.dumps({"approved": False, "notes": "still bad"}),
        content_type="application/json",
    )
    assert resp.status_code == 200

    with Storage() as db:
        session = db.get_session("s1")
        assert session["status"] == "needs_review"


def test_setup_endpoint_requires_passphrase_and_code(client):
    resp = client.post("/setup", data=json.dumps({}), content_type="application/json")
    assert resp.status_code == 400
    assert resp.get_json()["success"] is False


def test_setup_endpoint_success(client, monkeypatch):
    monkeypatch.setattr("server.crypto._fetch_secrets_from_github", lambda: "encrypted-blob")
    monkeypatch.setattr("server.crypto._derive_passphrase_only_key", lambda p: b"fake-key")
    monkeypatch.setattr("server.crypto.decrypt_data", lambda blob, key: b"JBSWY3DPEHPK3PXP")
    monkeypatch.setattr("server.crypto.verify_totp_code", lambda secret, code: True)

    resp = client.post(
        "/setup",
        data=json.dumps({"passphrase": "correct-horse", "totp_code": "123456"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    # The encryption key itself must never appear in the response.
    assert "encryption_key" not in data


def test_setup_endpoint_wrong_passphrase_returns_401(client, monkeypatch):
    def raise_invalid(blob, key):
        raise ValueError("bad token")

    monkeypatch.setattr("server.crypto._fetch_secrets_from_github", lambda: "encrypted-blob")
    monkeypatch.setattr("server.crypto._derive_passphrase_only_key", lambda p: b"wrong-key")
    monkeypatch.setattr("server.crypto.decrypt_data", raise_invalid)

    resp = client.post(
        "/setup",
        data=json.dumps({"passphrase": "wrong-passphrase", "totp_code": "123456"}),
        content_type="application/json",
    )
    assert resp.status_code == 401
    assert resp.get_json()["success"] is False


def test_setup_endpoint_wrong_totp_returns_401(client, monkeypatch):
    monkeypatch.setattr("server.crypto._fetch_secrets_from_github", lambda: "encrypted-blob")
    monkeypatch.setattr("server.crypto._derive_passphrase_only_key", lambda p: b"fake-key")
    monkeypatch.setattr("server.crypto.decrypt_data", lambda blob, key: b"JBSWY3DPEHPK3PXP")
    monkeypatch.setattr("server.crypto.verify_totp_code", lambda secret, code: False)

    resp = client.post(
        "/setup",
        data=json.dumps({"passphrase": "correct-horse", "totp_code": "000000"}),
        content_type="application/json",
    )
    assert resp.status_code == 401
    assert resp.get_json()["success"] is False


def test_sync_endpoint_requires_passphrase_and_code(client):
    resp = client.post("/sync", data=json.dumps({}), content_type="application/json")
    assert resp.status_code == 400


def test_sync_endpoint_rejects_bad_direction(client):
    resp = client.post(
        "/sync",
        data=json.dumps({"passphrase": "p", "totp_code": "123456", "direction": "sideways"}),
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_sync_endpoint_invalid_credentials_returns_401(client, monkeypatch):
    def raise_invalid(passphrase, totp_code):
        raise ValueError("Invalid passphrase")

    monkeypatch.setattr("server.crypto.resolve_encryption_key", raise_invalid)

    resp = client.post(
        "/sync",
        data=json.dumps({"passphrase": "wrong", "totp_code": "000000"}),
        content_type="application/json",
    )
    assert resp.status_code == 401
    assert "error" in resp.get_json()


class _FakeSyncWorker:
    """Mirrors the REAL shapes SyncWorker's methods return - not a
    hand-picked flat dict. This matters: pull_from_github()/
    push_to_github() each return a flat {direction, files_changed,
    conflicts, [reindexed]} dict, but sync() wraps both into
    {"pull": ..., "push": ..., "reindexed": N} - a fake that returned
    the flat shape from a mocked .sync() previously let
    result["files_changed"] being undefined in production go undetected,
    since the real sync()'s output never has that key at the top level.
    """

    instances = []

    def __init__(self, encryption_key):
        self.encryption_key = encryption_key
        self.calls = []
        _FakeSyncWorker.instances.append(self)

    def pull_from_github(self):
        self.calls.append("pull")
        return {"direction": "pull", "files_changed": 3, "conflicts": 0, "reindexed": 2}

    def push_to_github(self):
        self.calls.append("push")
        return {"direction": "push", "files_changed": 2, "conflicts": 0}

    def sync(self, direction="bidirectional"):
        self.calls.append(f"sync:{direction}")
        return {
            "pull": {"direction": "pull", "files_changed": 3, "conflicts": 0, "reindexed": 2},
            "push": {"direction": "push", "files_changed": 2, "conflicts": 0},
            "reindexed": 2,
        }


def test_sync_endpoint_success_defaults_to_bidirectional(client, monkeypatch):
    monkeypatch.setattr("server.crypto.resolve_encryption_key", lambda p, c: b"fake-key")
    _FakeSyncWorker.instances = []
    monkeypatch.setattr("src.sync.SyncWorker", _FakeSyncWorker)

    resp = client.post(
        "/sync",
        data=json.dumps({"passphrase": "correct-horse", "totp_code": "123456"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    # Flattened from the nested pull+push sync() result: 3 + 2 files changed.
    assert data["files_changed"] == 5
    assert data["conflicts"] == 0
    assert data["reindexed"] == 2
    assert _FakeSyncWorker.instances[0].calls == ["sync:bidirectional"]
    # The key server.py derived must never leak back into the response.
    assert "encryption_key" not in data


def test_sync_endpoint_pull_only_uses_flat_pull_result(client, monkeypatch):
    monkeypatch.setattr("server.crypto.resolve_encryption_key", lambda p, c: b"fake-key")
    _FakeSyncWorker.instances = []
    monkeypatch.setattr("src.sync.SyncWorker", _FakeSyncWorker)

    resp = client.post(
        "/sync",
        data=json.dumps({"passphrase": "correct-horse", "totp_code": "123456", "direction": "pull"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["files_changed"] == 3
    assert data["reindexed"] == 2
    assert _FakeSyncWorker.instances[0].calls == ["pull"]


def test_sync_endpoint_push_only_uses_flat_push_result(client, monkeypatch):
    monkeypatch.setattr("server.crypto.resolve_encryption_key", lambda p, c: b"fake-key")
    _FakeSyncWorker.instances = []
    monkeypatch.setattr("src.sync.SyncWorker", _FakeSyncWorker)

    resp = client.post(
        "/sync",
        data=json.dumps({"passphrase": "correct-horse", "totp_code": "123456", "direction": "push"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["files_changed"] == 2
    # push_to_github() never returns a "reindexed" key - endpoint must default it.
    assert data["reindexed"] == 0
    assert _FakeSyncWorker.instances[0].calls == ["push"]


def test_sync_endpoint_collects_before_syncing(client, monkeypatch):
    import src.orchestration as orchestration_module

    monkeypatch.setattr("server.crypto.resolve_encryption_key", lambda p, c: b"fake-key")
    _FakeSyncWorker.instances = []
    monkeypatch.setattr("src.sync.SyncWorker", _FakeSyncWorker)

    calls = []
    monkeypatch.setattr(
        orchestration_module, "run_collection",
        lambda fail_fast=False: calls.append(1) or {"new": 0, "errors": 0, "total": 0, "sources": {}},
    )

    resp = client.post(
        "/sync",
        data=json.dumps({"passphrase": "correct-horse", "totp_code": "123456"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert len(calls) == 1


def test_sync_endpoint_collect_failure_does_not_block_sync(client, monkeypatch):
    import src.orchestration as orchestration_module

    monkeypatch.setattr("server.crypto.resolve_encryption_key", lambda p, c: b"fake-key")
    _FakeSyncWorker.instances = []
    monkeypatch.setattr("src.sync.SyncWorker", _FakeSyncWorker)

    def failing_collect(fail_fast=False):
        raise RuntimeError("boom")

    monkeypatch.setattr(orchestration_module, "run_collection", failing_collect)

    resp = client.post(
        "/sync",
        data=json.dumps({"passphrase": "correct-horse", "totp_code": "123456"}),
        content_type="application/json",
    )
    assert resp.status_code == 200


def test_sync_endpoint_sync_failure_returns_500(client, monkeypatch):
    monkeypatch.setattr("server.crypto.resolve_encryption_key", lambda p, c: b"fake-key")

    class FailingSyncWorker:
        def __init__(self, encryption_key):
            pass

        def pull_from_github(self):
            raise RuntimeError("no git repository at that path")

    monkeypatch.setattr("src.sync.SyncWorker", FailingSyncWorker)

    resp = client.post(
        "/sync",
        data=json.dumps({"passphrase": "correct-horse", "totp_code": "123456", "direction": "pull"}),
        content_type="application/json",
    )
    assert resp.status_code == 500
    assert "error" in resp.get_json()


@pytest.fixture
def import_dir(tmp_path, monkeypatch):
    """Isolate /import's writes from the real ~/.claude-search-library archive."""
    target = tmp_path / "raw_exports" / "claude-ai"
    monkeypatch.setattr("server.RAW_EXPORTS_CLAUDE_AI_DIR", target)
    return target


def test_import_endpoint_requires_sessions_list(client, import_dir):
    resp = client.post("/import", data=json.dumps({}), content_type="application/json")
    assert resp.status_code == 400


def test_import_endpoint_rejects_non_list(client, import_dir):
    resp = client.post(
        "/import",
        data=json.dumps({"sessions": {"not": "a list"}}),
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_import_endpoint_rejects_non_object_items(client, import_dir):
    resp = client.post(
        "/import",
        data=json.dumps({"sessions": ["just a string"]}),
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_import_endpoint_rejects_more_than_max_sessions_per_call(client, import_dir):
    import server

    too_many = [{"id": str(i)} for i in range(server.MAX_IMPORT_SESSIONS_PER_CALL + 1)]
    resp = client.post(
        "/import",
        data=json.dumps({"sessions": too_many}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert "limit" in resp.get_json()["error"]


def test_import_endpoint_writes_files_to_claude_ai_export_dir(client, import_dir):
    resp = client.post(
        "/import",
        data=json.dumps({"sessions": [{"title": "chat one"}, {"title": "chat two"}]}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["imported"] == 2
    assert len(data["files"]) == 2

    written = list(import_dir.glob("*.json"))
    assert len(written) == 2
    contents = [json.loads(f.read_text(encoding="utf-8"))["title"] for f in written]
    assert sorted(contents) == ["chat one", "chat two"]


def test_import_export_endpoint_requires_file(client, import_dir):
    resp = client.post("/import-export", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_import_export_endpoint_converts_real_export_json(client, import_dir):
    import io

    conversations = [
        {
            "uuid": "conv-1",
            "name": "Debugging a race condition",
            "created_at": "2026-07-30T14:22:00Z",
            "chat_messages": [
                {"sender": "human", "text": "Why does this deadlock?", "created_at": "2026-07-30T14:22:05Z"},
                {"sender": "assistant", "text": "Check lock ordering.", "created_at": "2026-07-30T14:22:15Z"},
            ],
        }
    ]
    data = {"file": (io.BytesIO(json.dumps(conversations).encode("utf-8")), "conversations.json")}

    resp = client.post("/import-export", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["converted"] == 1

    written = list(import_dir.glob("*.json"))
    assert len(written) == 1
    converted = json.loads(written[0].read_text(encoding="utf-8"))
    assert converted["id"] == "conv-1"
    assert converted["title"] == "Debugging a race condition"
    assert converted["messages"][0]["role"] == "user"


def test_import_export_endpoint_rejects_bad_zip(client, import_dir):
    import io

    data = {"file": (io.BytesIO(b"not a real zip"), "export.zip")}
    resp = client.post("/import-export", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_reprocess_endpoint_requires_confirm_when_session_ids_omitted(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    with Storage() as db:
        db.insert_session(_session("s1", status="needs_review"))

    resp = client.post("/review/reprocess", data=json.dumps({}), content_type="application/json")

    assert resp.status_code == 400
    assert "confirm" in resp.get_json()["error"]


def test_reprocess_endpoint_explicit_session_ids_does_not_require_confirm(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(
        "src.processor.process_batch",
        lambda targets, api_key, batch_size: {"succeeded": targets, "failed": [], "needs_review": []},
    )
    with Storage() as db:
        db.insert_session(_session("s1", status="needs_review"))

    resp = client.post(
        "/review/reprocess",
        data=json.dumps({"session_ids": ["s1"]}),
        content_type="application/json",
    )

    assert resp.status_code == 200
    assert resp.get_json()["succeeded"] == ["s1"]


def test_reprocess_endpoint_rejects_more_than_max_per_call(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    too_many = [f"s{i}" for i in range(server.MAX_REPROCESS_PER_CALL + 1)]
    resp = client.post(
        "/review/reprocess",
        data=json.dumps({"session_ids": too_many}),
        content_type="application/json",
    )

    assert resp.status_code == 400
    assert "limit" in resp.get_json()["error"]


def test_costs_endpoint_returns_report(client):
    from src.storage import Storage

    with Storage() as db:
        db.insert_session(_session("s1"))
        db.log_api_cost(
            "s1", "claude-haiku-4-5", input_tokens=1000, output_tokens=1000,
            cost_usd=0.006, called_at="2026-08-01T00:00:00+00:00",
        )

    resp = client.get("/costs")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["calls"] == 1
    assert data["total_cost_usd"] == pytest.approx(0.006)
    assert data["period"] == "all-time"


def test_costs_endpoint_scoped_to_month(client):
    from src.storage import Storage

    with Storage() as db:
        db.insert_session(_session("s1"))
        db.log_api_cost(
            "s1", "claude-haiku-4-5", input_tokens=1000, output_tokens=1000,
            cost_usd=0.006, called_at="2026-07-01T00:00:00+00:00",
        )

    resp = client.get("/costs?month=2026-08")
    assert resp.status_code == 200
    assert resp.get_json()["calls"] == 0


def test_costs_endpoint_rejects_month_and_quarter_together(client):
    resp = client.get("/costs?month=2026-08&quarter=2026-Q3")
    assert resp.status_code == 400
