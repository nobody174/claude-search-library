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

    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        yield c


def test_search_endpoint_missing_query_returns_400(client):
    resp = client.get("/search")
    assert resp.status_code == 400


def test_search_endpoint_returns_results(client, monkeypatch):
    monkeypatch.setattr(
        "server.run_search",
        lambda query, mode="semantic", top_k=10: [
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

    def fake_search(query, mode="semantic", top_k=10):
        captured["mode"] = mode
        return []

    monkeypatch.setattr("server.run_search", fake_search)

    resp = client.get("/search?q=minecraft")
    assert resp.status_code == 200
    assert captured["mode"] == "hybrid"
    assert resp.get_json()["mode"] == "hybrid"


def test_search_endpoint_accepts_explicit_mode(client, monkeypatch):
    captured = {}

    def fake_search(query, mode="semantic", top_k=10):
        captured["mode"] = mode
        return []

    monkeypatch.setattr("server.run_search", fake_search)

    resp = client.get("/search?q=minecraft&mode=keyword")
    assert resp.status_code == 200
    assert captured["mode"] == "keyword"
    assert resp.get_json()["mode"] == "keyword"
    assert resp.get_json()["query"] == "minecraft"


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
