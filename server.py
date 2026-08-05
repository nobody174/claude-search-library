"""Flask REST API server for Claude Search Library."""
from __future__ import annotations

import secrets
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from src import crypto
from src.search import search as run_search
from src.storage import Storage

PUBLIC_DIR = Path(__file__).resolve().parent / "public"
SRC_DIR = Path(__file__).resolve().parent / "src"

# python-dotenv has been a listed dependency since day one but was never
# actually invoked anywhere - every prior run of this server only ever
# saw ANTHROPIC_API_KEY/etc because a human (or an agent) manually
# exported .env into the shell first. Loading it here means server.py
# also works when double-clicked (e.g. from a .bat launcher), which has
# no shell environment to inherit from. load_dotenv() is a no-op if the
# vars are already set (e.g. by that same manual shell export), so this
# doesn't change behavior for anyone already doing that.
load_dotenv(Path(__file__).resolve().parent / ".env")

app = Flask(__name__)
CORS(app, origins=["localhost", "127.0.0.1"])

# --- Session gate ------------------------------------------------------
# Every route except the ones in _PUBLIC_ROUTES used to be reachable with
# zero credentials at all: /setup and /sync were the only routes that ever
# checked a passphrase/TOTP, so anyone who could reach this server's port
# (which binds 0.0.0.0 by design, for LAN/phone access - see CLAUDE.md's
# iPhone setup instructions) could read the full search index, session
# detail, and cost data, or trigger a real-money reprocess call, without
# ever proving they know the passphrase. The web UI's "Unlock Device"
# screen was purely client-side (a localStorage flag), never enforced
# server-side. Found via a full project security review, closed here with
# a short-lived server-side session issued only after /setup verifies the
# real passphrase + TOTP.
#
# In-memory only (not persisted) - a server restart requires re-unlocking,
# which is the right failure mode for a security boundary. Token ->
# expiry timestamp; SESSION_TTL_SECONDS matches crypto.py's existing
# SESSION_CACHE_TTL_SECONDS convention for "how long is a personal-machine
# unlock considered valid" so the two don't drift out of sync with each
# other for no reason.
SESSION_COOKIE_NAME = "csl_session"
SESSION_TTL_SECONDS = 30 * 60
_sessions: dict[str, float] = {}

# Both _sessions and _setup_attempts only ever dropped entries lazily, on
# next access to that *same* token/IP - an expired session nobody re-checks,
# or a lockout IP that never comes back, just sat in memory forever. Never
# actually a problem at personal-machine scale/uptime, but a real
# unbounded-growth bug in principle (flagged, low severity, in the
# 2026-08-05 review's Project Reviewer round 2). Opportunistic sweep here
# instead of a background thread - simplest fix that actually bounds
# growth, capped to run at most once per interval so it doesn't add
# per-request overhead.
_PRUNE_INTERVAL_SECONDS = 10 * 60
_last_prune_at = 0.0


def _prune_stale_entries() -> None:
    global _last_prune_at
    now = time.time()
    if now - _last_prune_at < _PRUNE_INTERVAL_SECONDS:
        return
    _last_prune_at = now
    for token, expiry in list(_sessions.items()):
        if now > expiry:
            del _sessions[token]
    cutoff = now - SETUP_LOCKOUT_SECONDS
    for ip, attempts in list(_setup_attempts.items()):
        recent = [t for t in attempts if t > cutoff]
        if recent:
            _setup_attempts[ip] = recent
        else:
            del _setup_attempts[ip]

# GET / and GET /src/<path> must stay reachable pre-unlock - that's the
# page and script that render the Unlock Device screen itself. /setup
# must stay reachable to actually perform the unlock.
_PUBLIC_ROUTES = {("GET", "/"), ("POST", "/setup")}


def _create_session() -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time() + SESSION_TTL_SECONDS
    return token


def _session_valid(token: Optional[str]) -> bool:
    if not token or token not in _sessions:
        return False
    if time.time() > _sessions[token]:
        del _sessions[token]
        return False
    return True


def _invalidate_session(token: Optional[str]) -> None:
    if token:
        _sessions.pop(token, None)


# --- /setup brute-force protection --------------------------------------
# The session gate above stops unauthenticated access, but /setup itself
# had no limit on how many passphrase+TOTP guesses could be thrown at it -
# Argon2id makes each guess expensive and TOTP narrows the window, but
# "expensive per guess" isn't the same as "bounded total guesses". Found
# via a Devil's Advocate pass on the session-gate fix itself. Per-source-IP
# lockout, in-memory (resets on restart, same as sessions - acceptable for
# a personal-machine security boundary).
SETUP_MAX_ATTEMPTS = 5
SETUP_LOCKOUT_SECONDS = 15 * 60
_setup_attempts: dict[str, list] = {}  # ip -> [timestamp, ...] of recent failures


def _setup_locked_out(ip: str) -> bool:
    cutoff = time.time() - SETUP_LOCKOUT_SECONDS
    attempts = [t for t in _setup_attempts.get(ip, []) if t > cutoff]
    _setup_attempts[ip] = attempts
    return len(attempts) >= SETUP_MAX_ATTEMPTS


def _record_setup_failure(ip: str) -> None:
    _setup_attempts.setdefault(ip, []).append(time.time())


def _clear_setup_failures(ip: str) -> None:
    _setup_attempts.pop(ip, None)


@app.before_request
def _require_session():
    _prune_stale_entries()
    if request.method == "OPTIONS":
        return None  # CORS preflight
    if (request.method, request.path) in _PUBLIC_ROUTES:
        return None
    if request.method == "GET" and request.path.startswith("/src/"):
        return None
    if not _session_valid(request.cookies.get(SESSION_COOKIE_NAME)):
        return jsonify({"error": "unlock required"}), 401
    return None


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
    ip = request.remote_addr or "unknown"
    if _setup_locked_out(ip):
        return jsonify({
            "success": False,
            "error": f"Too many failed attempts. Try again in up to {SETUP_LOCKOUT_SECONDS // 60} minutes.",
        }), 429

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
        _record_setup_failure(ip)
        return jsonify({"success": False, "error": "invalid passphrase"}), 401

    if not crypto.verify_totp_code(totp_secret, totp_code):
        _record_setup_failure(ip)
        return jsonify({"success": False, "error": "invalid TOTP code"}), 401

    _clear_setup_failures(ip)
    response = jsonify({"success": True})
    response.set_cookie(
        SESSION_COOKIE_NAME, _create_session(),
        max_age=SESSION_TTL_SECONDS, httponly=True, samesite="Strict",
        # secure=True whenever the request actually arrived over HTTPS, so
        # this automatically tightens if TLS is ever added, without
        # forcing it now - this server currently runs over plain HTTP by
        # design (LAN/phone access per CLAUDE.md), and browsers refuse to
        # honor Secure cookies set over a non-HTTPS LAN origin at all, so
        # hardcoding secure=True would just silently break login rather
        # than protect anything. The residual risk this doesn't close -
        # the session cookie still crosses the LAN in cleartext without
        # TLS - needs a real HTTPS setup (cert management, phone trust
        # prompts) to fix properly; flagged, not silently decided here.
        secure=request.is_secure,
    )
    return response


@app.route("/logout", methods=["POST"])
def logout_endpoint():
    """Invalidate this browser's session server-side. Called from the web
    UI's Lock button - previously Lock only cleared client-side storage,
    so a session cookie captured before locking (e.g. by someone else on
    the same LAN who'd already reached an unlocked tab) stayed valid on
    the server indefinitely. Always returns success even with no/an
    already-invalid cookie, since the end state (no valid session) is the
    same either way."""
    _invalidate_session(request.cookies.get(SESSION_COOKIE_NAME))
    response = jsonify({"success": True})
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


@app.route("/search", methods=["GET"])
def search_endpoint():
    """GET /search?q=QUERY&mode=hybrid&top_k=10&filters=<url-encoded JSON>

    mode: "semantic" (ChromaDB, by meaning) | "keyword" (FTS5, fast) |
    "hybrid" (both, default — semantic results preferred, FTS5 fills gaps
    when semantic is slow or sparse; see src/search.py::hybrid_search).

    filters: optional JSON object matching src/search.py's filter shape,
    e.g. {"source": "claude-code", "device": "desktop",
    "tags": ["minecraft"], "date_range": {"start": "...", "end": "..."}}.
    """
    import json as _json

    query = request.args.get("q", "")
    top_k = int(request.args.get("top_k", 10))
    mode = request.args.get("mode", "hybrid")

    filters = None
    raw_filters = request.args.get("filters")
    if raw_filters:
        try:
            filters = _json.loads(raw_filters)
        except ValueError:
            return jsonify({"error": "'filters' must be valid JSON"}), 400

    if not query:
        return jsonify({"error": "missing required query parameter 'q'"}), 400

    start = time.monotonic()
    results = run_search(query, mode=mode, top_k=top_k, filters=filters)
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


@app.route("/session/<session_id>/related", methods=["GET"])
def related_sessions_endpoint(session_id: str):
    """GET /session/<id>/related — other sessions sharing the most tags,
    ranked by overlap count. Personal-library scale (dozens-hundreds of
    sessions), so an in-Python pass over all summaries is fine; no need
    for a real similarity index on top of the existing tag data."""
    limit = min(int(request.args.get("limit", 5)), 20)

    with Storage() as db:
        summary = db.get_summary(session_id)
        own_tags = set((summary or {}).get("tags") or [])
        if not own_tags:
            return jsonify({"related": []})

        candidates = []
        for s in db.get_all_sessions():
            if s["id"] == session_id or s.get("status") != "processed":
                continue
            other_summary = db.get_summary(s["id"])
            other_tags = set((other_summary or {}).get("tags") or [])
            overlap = own_tags & other_tags
            if overlap:
                candidates.append((len(overlap), s, other_summary, sorted(overlap)))

    candidates.sort(key=lambda c: c[0], reverse=True)
    return jsonify({
        "related": [
            {
                "session_id": s["id"],
                "title": s.get("title"),
                "tldr": (summ or {}).get("tldr"),
                "shared_tags": tags,
            }
            for _, s, summ, tags in candidates[:limit]
        ]
    })


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

    # Collect from every local source first - notably the claude-desktop
    # collector, whose freshly-cached conversations only exist on this
    # machine until collected - so a sync triggered from the web UI
    # includes anything new without the user having to remember to run
    # `cli.py collect` separately first. Best-effort: a collector error
    # here shouldn't block the sync the user actually asked for.
    try:
        from src.orchestration import run_collection

        run_collection(fail_fast=False)
    except Exception as e:
        app.logger.warning("Pre-sync collect failed: %s", e)

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


@app.route("/import-export", methods=["POST"])
def import_export_endpoint():
    """POST /import-export (multipart/form-data, field "file")

    Accepts the real claude.ai Data Export a user downloads through
    Settings -> Export data — either the ZIP itself or its bare
    conversations.json — and converts it via
    src/claude_export_import.import_official_export() into the
    raw-export shape collect_from_claude_ai() watches. Unlike /import,
    this understands the actual official export schema
    (uuid/name/chat_messages[]/sender/text), not just pre-normalized
    session objects.
    """
    import tempfile
    import zipfile

    from src.claude_export_import import import_official_export

    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        return jsonify({"error": "no file uploaded (expected multipart field 'file')"}), 400

    suffix = ".zip" if uploaded.filename.lower().endswith(".zip") else ".json"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        uploaded.save(tmp.name)
        tmp_path = tmp.name

    try:
        result = import_official_export(tmp_path, output_dir=str(RAW_EXPORTS_CLAUDE_AI_DIR))
    except (ValueError, OSError, zipfile.BadZipFile) as e:
        return jsonify({"error": str(e)}), 400
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return jsonify(result)


@app.route("/costs", methods=["GET"])
def costs_endpoint():
    """GET /costs?month=YYYY-MM|&quarter=YYYY-QN — API spend report."""
    from src.cost_tracker import get_report

    month = request.args.get("month")
    quarter = request.args.get("quarter")
    if month and quarter:
        return jsonify({"error": "pass only one of 'month' or 'quarter'"}), 400

    try:
        report = get_report(month=month, quarter=quarter)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(report)


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

        # Real device registration lives in sync.py's sync_metadata.json
        # inside the git repo, not the SQL sync_metadata table
        # verify_archive() checks - storage.py can't read that file itself
        # without a circular import (sync.py already imports storage.py),
        # so this stat is corrected here instead, at the one layer that
        # already sees both. The SQL-table check inside verify_archive()
        # is left as-is (honest about what it actually checks - that
        # table just isn't what tracks devices in practice).
        try:
            from src.sync import DEFAULT_REPO_PATH, _read_sync_metadata

            metadata = _read_sync_metadata(DEFAULT_REPO_PATH)
            result["stats"]["devices_registered"] = len(metadata.get("devices", {}))
        except Exception as e:
            app.logger.warning("Failed to read real device count from sync_metadata.json: %s", e)

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


PENDING_STATUSES = ("needs_review", "new")


@app.route("/review", methods=["GET"])
def list_needs_review_endpoint():
    """GET /review — sessions awaiting (re)processing: failed ones
    (needs_review) and never-yet-summarized ones (new, whether freshly
    collected or reset by an in-place content update), for the UI's
    repair panel. Both are the same underlying action (process_batch),
    just different reasons a session ended up pending."""
    with Storage() as db:
        rows = [
            s for s in db.get_all_sessions() if s.get("status") in PENDING_STATUSES
        ]
    return jsonify({
        "sessions": [
            {
                "session_id": s["id"],
                "title": s.get("title"),
                "source": s.get("source"),
                "review_reason": s.get("review_reason") or ("new session" if s.get("status") == "new" else None),
            }
            for s in rows
        ]
    })


@app.route("/review/reprocess", methods=["POST"])
def reprocess_review_endpoint():
    """POST /review/reprocess {"session_ids": [...]} (omit/empty for "all
    pending" - needs_review + new) — re-runs summarization + indexing,
    same code path as `cli.py process`. Costs real API spend per session,
    same as any other summarization."""
    import os

    from src.processor import process_batch

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY is not set on the server"}), 500

    body = request.get_json(silent=True) or {}
    session_ids = body.get("session_ids")

    with Storage() as db:
        if session_ids:
            targets = session_ids
        else:
            targets = [
                s["id"] for s in db.get_all_sessions() if s.get("status") in PENDING_STATUSES
            ]

    if not targets:
        return jsonify({"succeeded": [], "failed": [], "needs_review": []})

    result = process_batch(targets, api_key=api_key, batch_size=len(targets))

    if result.get("succeeded"):
        with Storage() as db:
            db.export_summaries_to_jsonl()

    return jsonify(result)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Claude Search Library REST API")
    parser.add_argument("--port", type=int, default=7654)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument(
        "--no-tls", action="store_true",
        help="Serve plain HTTP instead of HTTPS. The session cookie set on "
             "/setup and /unlock then crosses the LAN in cleartext - only "
             "use this for pure-localhost dev work, not for real "
             "phone/LAN access (see CLAUDE.md's iPhone setup instructions).",
    )
    args = parser.parse_args()

    ssl_context = None
    if not args.no_tls:
        cert_dir = Path.home() / ".claude-search-library" / "certs"
        cert_path, key_path = cert_dir / "server.crt", cert_dir / "server.key"
        if cert_path.exists() and key_path.exists():
            ssl_context = (str(cert_path), str(key_path))
        else:
            print(
                f"No TLS cert found at {cert_dir} - falling back to plain "
                f"HTTP. Generate one with openssl or pass --no-tls to "
                f"silence this warning."
            )

    scheme = "https" if ssl_context else "http"
    print(f"Starting Claude Search Library on {scheme}://{args.host}:{args.port} ...")
    app.run(host=args.host, port=args.port, ssl_context=ssl_context)


if __name__ == "__main__":
    main()
