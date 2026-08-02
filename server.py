"""Flask REST API server for Claude Search Library."""
from __future__ import annotations

import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from src import crypto
from src.search import search as run_search
from src.storage import Storage

PUBLIC_DIR = Path(__file__).resolve().parent / "public"
SRC_DIR = Path(__file__).resolve().parent / "src"

app = Flask(__name__)
CORS(app, origins=["localhost", "127.0.0.1"])


@app.route("/", methods=["GET"])
def index_page():
    """Serve the web UI itself, so http://localhost:7654/ (or the LAN/phone
    equivalent per CLAUDE.md's iPhone setup instructions) is enough on its
    own — matches api.js's assumption that the page and the API share an
    origin, so relative fetch("/search") etc. calls resolve correctly.
    """
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.route("/src/<path:filename>", methods=["GET"])
def src_assets(filename: str):
    """Serve src/api.js, which index.html loads via a relative ../src/ path."""
    return send_from_directory(SRC_DIR, filename)

# Where /import writes uploaded Claude.ai export JSON — the same folder
# collect_from_claude_ai() already watches. A module-level constant (rather
# than inlining Path.home() in the route) so tests can monkeypatch it to a
# tmp_path instead of writing into the real user archive.
RAW_EXPORTS_CLAUDE_AI_DIR = Path.home() / ".claude-search-library" / "data" / "raw_exports" / "claude-ai"


@app.route("/setup", methods=["POST"])
def setup_endpoint():
    """Verify a device's passphrase + TOTP code against the existing setup.

    The server never returns the derived encryption key: it holds the
    server-side pieces (the encrypted TOTP secret, Argon2 params) needed to
    verify a device belongs to this library, but the actual encryption key
    is only ever derived client-side by src/api.js from the passphrase and
    TOTP secret the device already has locally (see Task 6's two-factor
    key derivation). This endpoint is authentication, not key distribution.
    """
    body = request.get_json(silent=True) or {}
    passphrase = body.get("passphrase")
    totp_code = body.get("totp_code")

    if not passphrase or not totp_code:
        return jsonify({"success": False, "error": "passphrase and totp_code are required"}), 400

    try:
        encrypted_totp = crypto._fetch_secrets_from_github()
        passphrase_key = crypto._derive_passphrase_only_key(passphrase)
        totp_secret = crypto.decrypt_data(encrypted_totp, passphrase_key).decode("utf-8")
    except Exception:
        return jsonify({"success": False, "error": "invalid passphrase"}), 401

    if not crypto.verify_totp_code(totp_secret, totp_code):
        return jsonify({"success": False, "error": "invalid TOTP code"}), 401

    return jsonify({"success": True})


@app.route("/search", methods=["GET"])
def search_endpoint():
    """GET /search?q=QUERY&mode=hybrid&top_k=10

    mode: "semantic" (ChromaDB, by meaning) | "keyword" (FTS5, fast) |
    "hybrid" (both, default — semantic results preferred, FTS5 fills gaps
    when semantic is slow or sparse; see src/search.py::hybrid_search).
    """
    query = request.args.get("q", "")
    top_k = int(request.args.get("top_k", 10))
    mode = request.args.get("mode", "hybrid")

    if not query:
        return jsonify({"error": "missing required query parameter 'q'"}), 400

    start = time.monotonic()
    results = run_search(query, mode=mode, top_k=top_k)
    query_time_ms = (time.monotonic() - start) * 1000

    return jsonify(
        {
            "query": query,
            "mode": mode,
            "results": results,
            "total_results": len(results),
            "query_time_ms": round(query_time_ms, 1),
        }
    )


@app.route("/session/<session_id>", methods=["GET"])
def session_endpoint(session_id: str):
    with Storage() as db:
        session = db.get_session(session_id)
        if session is None:
            return jsonify({"error": "session not found"}), 404
        summary = db.get_summary(session_id)

    raw_path = session.get("raw_file_path")
    response = dict(session)
    response["summary"] = summary
    response["link_to_raw"] = f"file://{raw_path}" if raw_path else None
    return jsonify(response)


@app.route("/stats", methods=["GET"])
def stats_endpoint():
    with Storage() as db:
        stats = db.get_stats()
        rows = db.conn.execute(
            "SELECT MAX(last_sync_at) as last_sync FROM sync_metadata"
        ).fetchone()

    stats["last_sync"] = rows["last_sync"] if rows else None
    return jsonify(stats)


@app.route("/sync", methods=["POST"])
def sync_endpoint():
    """POST /sync {passphrase, totp_code, direction}

    direction: "pull" | "push" | "bidirectional" (default).

    Credentials are required on every call and are never cached
    server-side between requests — see crypto.resolve_encryption_key's
    docstring for why. This is a deliberate tradeoff (re-auth on every
    sync click) accepted because server.py binds 0.0.0.0 by default for
    LAN/phone access, and an already-cached key would let anyone on the
    same network trigger a real sync without ever proving they know the
    passphrase or TOTP.
    """
    from src.sync import SyncWorker

    body = request.get_json(silent=True) or {}
    passphrase = body.get("passphrase")
    totp_code = body.get("totp_code")
    direction = body.get("direction", "bidirectional")

    if not passphrase or not totp_code:
        return jsonify({"error": "passphrase and totp_code are required"}), 400
    if direction not in ("pull", "push", "bidirectional"):
        return jsonify({"error": "direction must be 'pull', 'push', or 'bidirectional'"}), 400

    try:
        encryption_key = crypto.resolve_encryption_key(passphrase, totp_code)
    except ValueError as e:
        return jsonify({"error": str(e)}), 401

    try:
        worker = SyncWorker(encryption_key)
        # Mirror cli.py's sync command: pull_from_github()/push_to_github()
        # already return a flat {direction, files_changed, conflicts,
        # [reindexed]} dict for single-direction syncs. worker.sync() only
        # needs calling (and its nested {"pull":..., "push":..., "reindexed":
        # N} shape only needs flattening) for the bidirectional case -
        # calling worker.sync() unconditionally here previously left
        # result["files_changed"] undefined for every direction, since that
        # key only exists on the un-nested pull/push dicts, not on sync()'s
        # wrapper.
        if direction == "pull":
            result = worker.pull_from_github()
        elif direction == "push":
            result = worker.push_to_github()
            result.setdefault("reindexed", 0)
        else:
            raw = worker.sync(direction="bidirectional")
            pull_result = raw.get("pull") or {}
            push_result = raw.get("push") or {}
            result = {
                "direction": "bidirectional",
                "files_changed": pull_result.get("files_changed", 0) + push_result.get("files_changed", 0),
                "conflicts": pull_result.get("conflicts", 0) + push_result.get("conflicts", 0),
                "reindexed": raw.get("reindexed", 0),
            }
    except Exception as e:
        return jsonify({"error": f"Sync failed: {e}"}), 500

    return jsonify(result)


@app.route("/import", methods=["POST"])
def import_endpoint():
    """POST /import {sessions: [...]}

    Accepts one or more already-exported Claude.ai session JSON objects
    (the same shape produced by Settings -> Export data, one conversation
    per object) and writes each to the raw_exports/claude-ai folder that
    collect_from_claude_ai() already watches — letting the web UI replace
    manually placing files in ~/.claude-search-library/data/raw_exports/claude-ai/
    with a drag-and-drop upload. Does not run collection itself; the next
    `cli.py collect` (manual or --watch) picks these up same as always.
    """
    import json
    import uuid

    body = request.get_json(silent=True) or {}
    sessions = body.get("sessions")
    if not sessions or not isinstance(sessions, list):
        return jsonify({"error": "'sessions' must be a non-empty list of export objects"}), 400

    export_dir = RAW_EXPORTS_CLAUDE_AI_DIR
    export_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for session_obj in sessions:
        if not isinstance(session_obj, dict):
            return jsonify({"error": "each item in 'sessions' must be a JSON object"}), 400
        filename = f"import-{uuid.uuid4().hex}.json"
        (export_dir / filename).write_text(json.dumps(session_obj), encoding="utf-8")
        written.append(filename)

    return jsonify({"imported": len(written), "files": written})


@app.route("/devices", methods=["GET"])
def devices_endpoint():
    with Storage() as db:
        rows = db.conn.execute("SELECT * FROM sync_metadata").fetchall()
    return jsonify({"devices": [dict(r) for r in rows]})


@app.route("/health", methods=["GET"])
def health_endpoint():
    """GET /health — archive health status. Check this before syncing."""
    try:
        with Storage() as db:
            result = db.verify_archive(verbose=False)
        return jsonify(result), 200 if result["healthy"] else 503
    except Exception as e:
        return jsonify({"error": str(e), "healthy": False}), 500


@app.route("/review/<session_id>/approve", methods=["POST"])
def approve_review_endpoint(session_id: str):
    body = request.get_json(silent=True) or {}
    approved = body.get("approved", False)
    notes = body.get("notes")

    with Storage() as db:
        session = db.get_session(session_id)
        if session is None:
            return jsonify({"error": "session not found"}), 404

        if approved:
            db.mark_as_processed(session_id, "processed")
        updated_fields = {"review_reason": notes} if notes else {}
        if updated_fields:
            db.update_session(session_id, updated_fields)

    return jsonify({"session_id": session_id, "approved": bool(approved), "notes": notes})


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Claude Search Library REST API")
    parser.add_argument("--port", type=int, default=7654)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
