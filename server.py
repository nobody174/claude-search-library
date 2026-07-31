"""Flask REST API server for Claude Search Library."""
from __future__ import annotations

import time

from flask import Flask, jsonify, request
from flask_cors import CORS

from src import crypto
from src.search import search as run_search
from src.storage import Storage

app = Flask(__name__)
CORS(app, origins=["localhost", "127.0.0.1"])


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
    query = request.args.get("q", "")
    top_k = int(request.args.get("top_k", 10))
    mode = request.args.get("mode", "semantic")

    if not query:
        return jsonify({"error": "missing required query parameter 'q'"}), 400

    start = time.monotonic()
    results = run_search(query, mode=mode, top_k=top_k)
    query_time_ms = (time.monotonic() - start) * 1000

    return jsonify(
        {
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


@app.route("/devices", methods=["GET"])
def devices_endpoint():
    with Storage() as db:
        rows = db.conn.execute("SELECT * FROM sync_metadata").fetchall()
    return jsonify({"devices": [dict(r) for r in rows]})


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
