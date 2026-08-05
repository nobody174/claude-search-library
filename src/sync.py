#
# Claude Search Library
# Author:  nobody174
# Repo:    https://github.com/nobody174/claude-search-library
# Patreon: https://www.patreon.com/c/Nobody174
# License: MIT
# "It's never too late to give up!"
#

"""Distributed sync module for Claude Search Library.

Syncs encrypted session data across devices via a GitHub repo acting as
the transport layer. Each device is autonomous: sync is push + pull +
CRDT merge, with no central hub. Conflict resolution is Last-Write-Wins
on timestamp, delegated to cr-sqlite where available (see storage.py).
"""
from __future__ import annotations

import base64
import json
import logging
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from git import GitCommandError, InvalidGitRepositoryError, Repo

from src import crypto
from src.storage import CR_SQLITE_CRR_TABLES, Storage

logger = logging.getLogger(__name__)

LOG_PATH = Path.home() / ".claude-search-library" / "logs" / "sync.log"
DEFAULT_REPO_PATH = Path.home() / ".claude-search-library" / "repo"
DEFAULT_SYNC_INTERVAL_SECONDS = 300

ENCRYPTED_RAW_CHATS_DIR = "encrypted_raw_chats"
SECRETS_FILENAME = "secrets.enc"
SYNC_METADATA_FILENAME = "sync_metadata.json"

# cr-sqlite changeset transport, replacing ENCRYPTED_SESSIONS_DIR/
# ENCRYPTED_SUMMARIES_DIR's whole-row-per-file model for the two CRR
# tables (sessions, summaries - see storage.CR_SQLITE_CRR_TABLES). One
# encrypted file per push, named by the crsql db_version it covers,
# under a per-device subdirectory so devices never collide on filenames.
# Applying a changeset is idempotent (that's the whole point of a CRDT),
# so pull just re-applies every changeset file from every other device on
# every pull rather than tracking a per-file "already applied" watermark -
# simpler and safe at this project's scale (dozens-hundreds of files).
CHANGESETS_DIR = "changesets"
_CRSQL_CHANGES_COLUMNS = ["table", "pk", "cid", "val", "col_version", "db_version", "site_id", "cl", "seq"]
_CRSQL_CHANGES_COLUMNS_SQL = ",".join(f'"{c}"' for c in _CRSQL_CHANGES_COLUMNS)

# Bumped whenever the sync transport's on-disk shape changes in a way
# that's silently misread by older code - like this session's move from
# whole-row files to changesets. A device running code from *before* this
# constant existed at all (e.g. a desktop that hasn't pulled the latest
# code yet) has no way to know to check this - that half of the risk is
# procedural, not fixable in code (update the CODE repo before ever
# running an old checkout against a migrated data repo). What this DOES
# protect: any *future* protocol bump, where new code correctly refuses
# to silently proceed against a data repo from a newer protocol version
# it doesn't understand, instead of reporting a false "0 changes, all
# good". Found via a Release Manager pass, prompted by discovering 114
# stale pre-migration files still sitting in the data repo that an
# not-yet-updated desktop would otherwise read as if current.
SYNC_PROTOCOL_VERSION = 2
SYNC_PROTOCOL_VERSION_FILENAME = "sync_protocol_version"


def _check_protocol_version(repo_path: Path) -> None:
    version_path = repo_path / SYNC_PROTOCOL_VERSION_FILENAME
    if not version_path.exists():
        return
    remote_version = int(version_path.read_text(encoding="utf-8").strip() or "1")
    if remote_version > SYNC_PROTOCOL_VERSION:
        raise RuntimeError(
            f"This data repo is on sync protocol version {remote_version}, but this "
            f"device's code only understands up to version {SYNC_PROTOCOL_VERSION}. "
            f"Update claude-search-library's code on this device before syncing, or "
            f"you will silently miss real changes rather than see an error like this one."
        )


def _stamp_protocol_version_if_needed(repo_path: Path) -> Optional[str]:
    """Write the current protocol version file if it's missing or stale.
    Returns the relative filename if it needs to be added to this push's
    commit, or None if it's already up to date (avoid a spurious commit
    on every no-op sync just to rewrite an unchanged value)."""
    version_path = repo_path / SYNC_PROTOCOL_VERSION_FILENAME
    current = version_path.read_text(encoding="utf-8").strip() if version_path.exists() else None
    if current == str(SYNC_PROTOCOL_VERSION):
        return None
    version_path.write_text(str(SYNC_PROTOCOL_VERSION), encoding="utf-8")
    return SYNC_PROTOCOL_VERSION_FILENAME


def _encode_changeset_row(row: dict) -> dict:
    """crsql_changes' pk/site_id columns are raw bytes; val's type follows
    the changed column's own affinity (TEXT/INTEGER/REAL/NULL/bytes).
    JSON can't represent bytes directly, so wrap any bytes value with a
    marker dict instead of blanket base64-encoding every field (which
    would also mangle real int/str/float values)."""

    def encode(v):
        return {"__b64__": base64.b64encode(v).decode("ascii")} if isinstance(v, bytes) else v

    return {k: encode(row[k]) for k in _CRSQL_CHANGES_COLUMNS}


def _decode_changeset_row(row: dict) -> tuple:
    def decode(v):
        return base64.b64decode(v["__b64__"]) if isinstance(v, dict) and "__b64__" in v else v

    return tuple(decode(row[k]) for k in _CRSQL_CHANGES_COLUMNS)


def _setup_file_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not any(isinstance(h, logging.FileHandler) and h.baseFilename == str(LOG_PATH) for h in logger.handlers):
        handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)


def _device_id() -> str:
    return socket.gethostname().replace(" ", "_").lower()


def _open_repo(repo_path: Path) -> Repo:
    try:
        return Repo(repo_path)
    except InvalidGitRepositoryError as e:
        raise RuntimeError(
            f"No git repository at {repo_path}. Clone the GitHub repo there first."
        ) from e


def _read_sync_metadata(repo_path: Path) -> dict:
    path = repo_path / SYNC_METADATA_FILENAME
    if not path.exists():
        return {"devices": {}}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_sync_metadata(repo_path: Path, metadata: dict) -> None:
    path = repo_path / SYNC_METADATA_FILENAME
    with open(path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)


def _update_device_metadata(
    repo_path: Path, pending_changes: int = 0, bump_push_checkpoint: bool = False,
    last_pushed_db_version: Optional[int] = None,
) -> None:
    """Update this device's sync_metadata.json entry.

    `last_sync_at`/`last_heartbeat` reflect "last time this device did any
    sync operation" (push or pull) — used only for the dashboard's "Last
    sync" display. They must NOT be used as the incremental-push
    checkpoint: pull_from_github() used to call this with no way to opt
    out, so a pull immediately followed by a push would stamp
    last_sync_at to *now*, and push_to_github()'s "only push sessions
    updated after last_sync_at" filter would then treat every real,
    never-before-pushed session as already synced (since their
    updated_at is always in the past relative to a pull that just
    happened) — silently skipping the push. `last_push_at` is a separate
    checkpoint, bumped only when bump_push_checkpoint=True (i.e. from
    push_to_github after a successful push), so pulling never resets it.

    `last_pushed_db_version` is this device's own crsql_db_version()
    watermark - the cr-sqlite changeset transport's equivalent of
    `last_push_at`, letting push_to_github() ask "what's changed locally
    since I last pushed?" without re-sending already-pushed changesets.
    Only updated when explicitly passed (mirrors bump_push_checkpoint).
    """
    metadata = _read_sync_metadata(repo_path)
    now = datetime.now(timezone.utc).isoformat()
    device_id = _device_id()
    existing = metadata.setdefault("devices", {}).get(device_id, {})
    entry = {
        "device_name": device_id,
        "last_sync_at": now,
        "last_heartbeat": now,
        "pending_changes": pending_changes,
        "last_push_at": now if bump_push_checkpoint else existing.get("last_push_at"),
        "last_pushed_db_version": (
            last_pushed_db_version if last_pushed_db_version is not None
            else existing.get("last_pushed_db_version", 0)
        ),
    }
    metadata["devices"][device_id] = entry
    _write_sync_metadata(repo_path, metadata)


def push_file(filename: str, content: str, repo_path: Optional[str] = None) -> None:
    """Write a single file at the repo root and commit + push it.

    Used by crypto.py to store the encrypted TOTP secret (secrets.enc).
    """
    _setup_file_logging()
    path = Path(repo_path) if repo_path else DEFAULT_REPO_PATH
    repo = _open_repo(path)

    file_path = path / filename
    file_path.write_text(content, encoding="utf-8")

    repo.index.add([str(file_path)])
    repo.index.commit(f"Update {filename}")
    repo.remote(name="origin").push()
    logger.info("pushed file=%s", filename)


def fetch_file(filename: str, repo_path: Optional[str] = None) -> str:
    """Pull latest and read a single file at the repo root.

    Used by crypto.py to fetch the encrypted TOTP secret (secrets.enc).
    """
    _setup_file_logging()
    path = Path(repo_path) if repo_path else DEFAULT_REPO_PATH
    repo = _open_repo(path)
    repo.remote(name="origin").pull()

    file_path = path / filename
    if not file_path.exists():
        raise FileNotFoundError(f"{filename} not found in repo at {path}")
    return file_path.read_text(encoding="utf-8")


class SyncWorker:
    """Orchestrates push/pull/merge sync between local SQLite+ChromaDB and GitHub."""

    def __init__(
        self,
        encryption_key: bytes,
        repo_path: Optional[str] = None,
        db_path: Optional[str] = None,
        chroma_path: Optional[str] = None,
    ):
        _setup_file_logging()
        self.encryption_key = encryption_key
        self.repo_path = Path(repo_path) if repo_path else DEFAULT_REPO_PATH
        self.db_path = db_path
        self.chroma_path = chroma_path

    def check_for_changes(self) -> int:
        """Count sessions whose content has changed since *that session*
        was last pushed - i.e. never pushed (synced_at is null) or edited
        since its last push (content timestamp newer than its own
        synced_at). Quick local SQLite check only — no network access.

        Deliberately per-session (sessions.synced_at), not a single
        device-level "last push" wall-clock checkpoint compared against
        each session's own content timestamp. That comparison is wrong
        for any newly-collected/imported session whose *content* predates
        this device's checkpoint - which is the common case for a bulk
        historical import (e.g. an official claude.ai export, or a
        newly-cached Cowork/desktop-app session for an old conversation):
        a session dated months ago looks "older than the last push" and
        gets silently skipped forever, even though it has genuinely never
        been pushed. Found via a real, reproducible case: importing a
        real 2026-07-26 Cowork conversation on 2026-08-04 was silently
        dropped from every subsequent push because 07-26 < 08-04.
        """
        with Storage(self.db_path) as db:
            sessions = db.get_all_sessions()

        changed = [
            s for s in sessions
            if not s.get("synced_at")
            or (s.get("updated_at") or s.get("created_at") or "") > s["synced_at"]
        ]
        return len(changed)

    def push_to_github(self) -> dict:
        """Push local changes to the GitHub repo: a cr-sqlite changeset file
        covering sessions+summaries (real per-column CRDT merge on pull -
        see storage.CR_SQLITE_CRR_TABLES), plus raw chat files for any
        session that changed.

        Raw-file selection still uses the original per-session
        (sessions.synced_at) check - see check_for_changes()'s docstring
        for why a single device-level checkpoint compared against each
        session's own content timestamp is wrong (it silently drops any
        newly-imported session whose content predates this device's
        checkpoint, e.g. bulk historical imports). The changeset itself
        uses its own, separate watermark (last_pushed_db_version) since
        crsql_db_version() is a whole-database counter, not per-session.
        """
        _setup_file_logging()
        repo = _open_repo(self.repo_path)
        _check_protocol_version(self.repo_path)
        device_id = _device_id()

        changesets_dir = self.repo_path / CHANGESETS_DIR / device_id
        raw_dir = self.repo_path / ENCRYPTED_RAW_CHATS_DIR
        changesets_dir.mkdir(parents=True, exist_ok=True)
        raw_dir.mkdir(parents=True, exist_ok=True)

        files_changed = []
        now = datetime.now(timezone.utc).isoformat()
        with Storage(self.db_path) as db:
            metadata = _read_sync_metadata(self.repo_path)
            last_pushed = metadata.get("devices", {}).get(device_id, {}).get("last_pushed_db_version", 0)

            rows = db.conn.execute(
                f'SELECT {_CRSQL_CHANGES_COLUMNS_SQL} FROM crsql_changes '
                f'WHERE db_version > ? AND site_id = crsql_site_id()',
                (last_pushed,),
            ).fetchall()

            new_last_pushed = last_pushed
            if rows:
                new_last_pushed = max(r["db_version"] for r in rows)
                changeset = [_encode_changeset_row(dict(r)) for r in rows]
                blob = crypto.encrypt_data(json.dumps(changeset).encode("utf-8"), self.encryption_key)
                changeset_path = changesets_dir / f"{new_last_pushed}.enc"
                changeset_path.write_text(blob, encoding="utf-8")
                files_changed.append(str(changeset_path.relative_to(self.repo_path)))

            sessions = db.get_all_sessions()
            for session in sessions:
                synced_at = session.get("synced_at")
                updated = session.get("updated_at") or session.get("created_at") or ""
                if synced_at and updated <= synced_at:
                    continue

                raw_path = session.get("raw_file_path")
                if raw_path and Path(raw_path).exists():
                    raw_content = Path(raw_path).read_bytes()
                    blob = crypto.encrypt_data(raw_content, self.encryption_key)
                    raw_out_path = raw_dir / f"{session['id']}_raw.enc"
                    raw_out_path.write_text(blob, encoding="utf-8")
                    files_changed.append(str(raw_out_path.relative_to(self.repo_path)))

                # synced_at/sync_version are local device bookkeeping, not
                # meaningful synced content - writing them to a CRR table
                # does generate a small extra changeset entry each push,
                # which is harmless noise at this project's scale (not
                # worth splitting into a separate local-only table yet).
                db.update_session(session["id"], {
                    "synced_at": now,
                    "sync_version": (session.get("sync_version") or 1) + 1,
                })

        _update_device_metadata(
            self.repo_path, pending_changes=0, bump_push_checkpoint=True,
            last_pushed_db_version=new_last_pushed,
        )

        if files_changed:
            version_file = _stamp_protocol_version_if_needed(self.repo_path)
            commit_files = files_changed + [SYNC_METADATA_FILENAME] + ([version_file] if version_file else [])
            repo.index.add(commit_files)
            repo.index.commit(f"Sync from {device_id}: {len(files_changed)} file(s)")
            repo.remote(name="origin").push()

        logger.info("push complete: device=%s files_changed=%d", device_id, len(files_changed))
        return {"direction": "push", "files_changed": len(files_changed), "conflicts": 0}

    def pull_from_github(self) -> dict:
        """Pull latest encrypted data from GitHub, decrypt, and merge locally.

        sessions/summaries arrive as cr-sqlite changesets (see
        CHANGESETS_DIR) - applying one is `INSERT INTO crsql_changes`,
        which is where the real per-column CRDT merge happens (two
        devices editing different fields of the same session both survive
        - see storage.CR_SQLITE_CRR_TABLES). This replaces the old
        whole-row-file + hand-written Last-Write-Wins comparison.
        """
        _setup_file_logging()
        repo = _open_repo(self.repo_path)

        # _update_device_metadata() (below, and at the end of this method)
        # writes SYNC_METADATA_FILENAME straight to the working tree without
        # committing it - harmless if a push follows immediately (push
        # commits it as part of its own commit), but calling pull twice
        # in a row with no intervening push - e.g. `cli.py sync --pull`
        # used repeatedly, or this device just wants a fresh read - leaves
        # a real uncommitted change that makes a plain `git pull` fail
        # outright ("local changes would be overwritten by merge"). Safe
        # to discard: it's pure local bookkeeping about to be rewritten by
        # this same pull's own _update_device_metadata() call anyway.
        metadata_path = self.repo_path / SYNC_METADATA_FILENAME
        if metadata_path.exists() and repo.is_dirty(path=SYNC_METADATA_FILENAME):
            repo.git.checkout("--", SYNC_METADATA_FILENAME)

        try:
            repo.remote(name="origin").pull()
        except GitCommandError as e:
            logger.error("pull failed: %s", e)
            raise

        _check_protocol_version(self.repo_path)

        changesets_root = self.repo_path / CHANGESETS_DIR
        device_id = _device_id()
        files_changed = 0
        rows_applied = 0
        conflicts = 0  # CRDT merge auto-resolves everything; nothing gets rejected.

        with Storage(self.db_path) as db:
            # Every other device's changeset files, oldest device-dir first
            # for determinism. Re-applying an already-applied changeset is
            # a safe no-op (idempotent by construction), so no per-file
            # "already applied" tracking is needed - see CHANGESETS_DIR's
            # module comment for why that's an acceptable tradeoff here.
            other_device_dirs = (
                sorted(d for d in changesets_root.iterdir() if d.is_dir() and d.name != device_id)
                if changesets_root.exists() else []
            )
            for device_dir in other_device_dirs:
                for enc_path in sorted(device_dir.glob("*.enc"), key=lambda p: int(p.stem)):
                    try:
                        decrypted = crypto.decrypt_data(enc_path.read_text(encoding="utf-8"), self.encryption_key)
                        changeset = json.loads(decrypted)
                    except Exception as e:
                        logger.error("failed to decrypt/parse %s: %s", enc_path, e)
                        continue

                    for row in changeset:
                        db.conn.execute(
                            f'INSERT INTO crsql_changes ({_CRSQL_CHANGES_COLUMNS_SQL}) '
                            f'VALUES (?,?,?,?,?,?,?,?,?)',
                            _decode_changeset_row(row),
                        )
                        rows_applied += 1
                    files_changed += 1
            db.conn.commit()

        _update_device_metadata(self.repo_path, pending_changes=0)

        reindexed = 0
        if files_changed > 0:
            # Reindexing lives here, inside pull_from_github() itself, not
            # in sync()'s wrapper logic - it must fire regardless of which
            # caller triggers a pull. It previously lived only in sync(),
            # so `cli.py sync --pull` (which calls pull_from_github()
            # directly, bypassing sync()) silently skipped it: a pulled
            # session landed in the database but was never embedded into
            # ChromaDB or indexed for keyword search, so search returned
            # nothing on the receiving device even though pull reported
            # success. Found via a real --join-device + --pull run on an
            # actual second machine.
            try:
                from src.embedder import reindex_all
                reindexed = reindex_all(db_path=self.db_path, chroma_path=self.chroma_path)
            except Exception as e:
                logger.warning("Failed to rebuild ChromaDB embeddings after pull: %s", e)
            try:
                self._reindex_search_index_and_fts5()
            except Exception as e:
                logger.warning("Failed to rebuild search_index/FTS5 after pull: %s", e)

        logger.info(
            "pull complete: files_changed=%d rows_applied=%d conflicts=%d reindexed=%d",
            files_changed, rows_applied, conflicts, reindexed,
        )
        return {
            "direction": "pull", "files_changed": files_changed, "rows_applied": rows_applied,
            "conflicts": conflicts, "reindexed": reindexed,
        }

    def _reindex_search_index_and_fts5(self) -> None:
        """Rebuild search_index + FTS5 for all processed sessions.

        reindex_all() (embedder.py) only rebuilds ChromaDB embeddings.
        Without this, a pulled session is findable by semantic search but
        not by keyword/hybrid search — the same gap process_batch() has
        fixed for locally-processed sessions, but pull_from_github() never
        touches search_index or the FTS5 table at all.
        """
        with Storage(self.db_path) as db:
            for session in db.get_all_sessions():
                if session.get("status") != "processed":
                    continue
                summary = db.get_summary(session["id"])
                if summary is None:
                    continue
                tldr = summary.get("tldr") or ""
                learnings = summary.get("learnings") or []
                patterns = summary.get("patterns") or []
                tags = summary.get("tags") or []
                searchable_text = " ".join(
                    [tldr, *(learnings if isinstance(learnings, list) else [str(learnings)]),
                     *(patterns if isinstance(patterns, list) else [str(patterns)])]
                ).strip()
                db.index_session(
                    session["id"], searchable_text,
                    keywords=",".join(tags) if isinstance(tags, list) else str(tags),
                )
            db.create_fts5_index()

    def sync(self, direction: str = "bidirectional") -> dict:
        """Orchestrate a full sync: pull (which reindexes on its own), then push.

        `direction` is one of "pull", "push", or "bidirectional". Reindexing
        (ChromaDB + search_index/FTS5) happens inside pull_from_github()
        itself so it also fires for direct pull_from_github() callers (e.g.
        `cli.py sync --pull`), not just through this method.
        Errors from any stage are logged and re-raised after cleanup.
        """
        _setup_file_logging()
        result = {"pull": None, "push": None, "reindexed": 0}
        try:
            if direction in ("pull", "bidirectional"):
                result["pull"] = self.pull_from_github()
                result["reindexed"] = result["pull"].get("reindexed", 0)

            if direction in ("push", "bidirectional"):
                result["push"] = self.push_to_github()

            logger.info("sync complete: direction=%s result=%s", direction, result)
            return result
        except Exception as e:
            logger.error("sync failed: direction=%s error=%s", direction, e)
            raise

    def daemon_loop(
        self,
        interval: int = DEFAULT_SYNC_INTERVAL_SECONDS,
        iterations: Optional[int] = None,
        collect_first: bool = True,
    ) -> None:
        """Run sync on a fixed interval, checking for local changes first.

        Exits silently (no network call) when there is nothing to push,
        but still pulls to catch changes from other devices.

        collect_first=True (default) runs every local collector - notably
        the claude-desktop collector, whose freshly-cached conversations
        only exist on this machine until collected - before each
        check-for-changes/sync pass, so a long-running `sync --watch`
        picks up new local data on its own rather than requiring a
        separate `collect` process running alongside it.
        """
        _setup_file_logging()
        count = 0
        while iterations is None or count < iterations:
            if collect_first:
                try:
                    from src.orchestration import run_collection

                    run_collection(fail_fast=False, db_path=self.db_path)
                except Exception as e:
                    logger.error("daemon: collect failed: %s", e)

            changed = self.check_for_changes()
            if changed > 0:
                logger.info("daemon: %d local change(s) detected, syncing", changed)
                try:
                    self.sync(direction="bidirectional")
                except Exception as e:
                    logger.error("daemon: sync failed: %s", e)
            else:
                logger.info("daemon: no local changes, pulling only")
                try:
                    self.pull_from_github()
                except Exception as e:
                    logger.error("daemon: pull failed: %s", e)

            count += 1
            if iterations is None or count < iterations:
                time.sleep(interval)


def main() -> None:
    import argparse

    from dotenv import load_dotenv

    # See server.py's matching load_dotenv() call.
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    parser = argparse.ArgumentParser(description="Claude Search Library sync")
    parser.add_argument("--pull", action="store_true", help="Pull only")
    parser.add_argument("--push", action="store_true", help="Push only")
    parser.add_argument("--daemon", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=DEFAULT_SYNC_INTERVAL_SECONDS)
    parser.add_argument("--watch", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.watch else logging.INFO)

    encryption_key = crypto.join_device_existing_setup()["encryption_key"]
    worker = SyncWorker(encryption_key=encryption_key)

    if args.daemon:
        worker.daemon_loop(interval=args.interval)
    elif args.pull:
        print(json.dumps(worker.pull_from_github(), indent=2))
    elif args.push:
        print(json.dumps(worker.push_to_github(), indent=2))
    else:
        print(json.dumps(worker.sync(), indent=2))


if __name__ == "__main__":
    main()

# Built with assistance from Claude Code by Anthropic.
