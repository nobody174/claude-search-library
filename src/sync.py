"""Distributed sync module for Claude Search Library.

Syncs encrypted session data across devices via a GitHub repo acting as
the transport layer. Each device is autonomous: sync is push + pull +
CRDT merge, with no central hub. Conflict resolution is Last-Write-Wins
on timestamp, delegated to cr-sqlite where available (see storage.py).
"""
from __future__ import annotations

import json
import logging
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from git import GitCommandError, InvalidGitRepositoryError, Repo

from src import crypto
from src.storage import Storage

logger = logging.getLogger(__name__)

LOG_PATH = Path.home() / ".claude-search-library" / "logs" / "sync.log"
DEFAULT_REPO_PATH = Path.home() / ".claude-search-library" / "repo"
DEFAULT_SYNC_INTERVAL_SECONDS = 300

ENCRYPTED_SUMMARIES_DIR = "encrypted_summaries"
ENCRYPTED_RAW_CHATS_DIR = "encrypted_raw_chats"
SECRETS_FILENAME = "secrets.enc"
SYNC_METADATA_FILENAME = "sync_metadata.json"


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


def _update_device_metadata(repo_path: Path, pending_changes: int = 0) -> None:
    metadata = _read_sync_metadata(repo_path)
    now = datetime.now(timezone.utc).isoformat()
    device_id = _device_id()
    metadata.setdefault("devices", {})[device_id] = {
        "device_name": device_id,
        "last_sync_at": now,
        "last_heartbeat": now,
        "pending_changes": pending_changes,
    }
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
        """Count sessions modified since this device's last sync.

        Quick local SQLite check only — no network access.
        """
        metadata = _read_sync_metadata(self.repo_path)
        device_id = _device_id()
        last_sync_at = metadata.get("devices", {}).get(device_id, {}).get("last_sync_at")

        with Storage(self.db_path) as db:
            sessions = db.get_all_sessions()

        if not last_sync_at:
            return len(sessions)

        changed = [
            s for s in sessions
            if (s.get("updated_at") or s.get("created_at") or "") > last_sync_at
        ]
        return len(changed)

    def push_to_github(self) -> dict:
        """Encrypt and push changed sessions/summaries to the GitHub repo."""
        _setup_file_logging()
        repo = _open_repo(self.repo_path)

        metadata = _read_sync_metadata(self.repo_path)
        device_id = _device_id()
        last_sync_at = metadata.get("devices", {}).get(device_id, {}).get("last_sync_at")

        summaries_dir = self.repo_path / ENCRYPTED_SUMMARIES_DIR
        raw_dir = self.repo_path / ENCRYPTED_RAW_CHATS_DIR
        summaries_dir.mkdir(parents=True, exist_ok=True)
        raw_dir.mkdir(parents=True, exist_ok=True)

        files_changed = []
        with Storage(self.db_path) as db:
            sessions = db.get_all_sessions()
            for session in sessions:
                updated = session.get("updated_at") or session.get("created_at") or ""
                if last_sync_at and updated <= last_sync_at:
                    continue

                summary = db.get_summary(session["id"])
                if summary is not None:
                    blob = crypto.encrypt_data(
                        json.dumps(summary).encode("utf-8"), self.encryption_key
                    )
                    summary_path = summaries_dir / f"{session['id']}_summary.enc"
                    summary_path.write_text(blob, encoding="utf-8")
                    files_changed.append(str(summary_path.relative_to(self.repo_path)))

                raw_path = session.get("raw_file_path")
                if raw_path and Path(raw_path).exists():
                    raw_content = Path(raw_path).read_bytes()
                    blob = crypto.encrypt_data(raw_content, self.encryption_key)
                    raw_out_path = raw_dir / f"{session['id']}_raw.enc"
                    raw_out_path.write_text(blob, encoding="utf-8")
                    files_changed.append(str(raw_out_path.relative_to(self.repo_path)))

        _update_device_metadata(self.repo_path, pending_changes=0)

        if files_changed:
            repo.index.add(files_changed + [SYNC_METADATA_FILENAME])
            repo.index.commit(f"Sync from {device_id}: {len(files_changed)} file(s)")
            repo.remote(name="origin").push()

        logger.info("push complete: device=%s files_changed=%d", device_id, len(files_changed))
        return {"direction": "push", "files_changed": len(files_changed), "conflicts": 0}

    def pull_from_github(self) -> dict:
        """Pull latest encrypted data from GitHub, decrypt, and merge locally."""
        _setup_file_logging()
        repo = _open_repo(self.repo_path)

        try:
            repo.remote(name="origin").pull()
        except GitCommandError as e:
            logger.error("pull failed: %s", e)
            raise

        summaries_dir = self.repo_path / ENCRYPTED_SUMMARIES_DIR
        files_changed = 0
        conflicts = 0

        with Storage(self.db_path) as db:
            for enc_path in sorted(summaries_dir.glob("*_summary.enc")) if summaries_dir.exists() else []:
                session_id = enc_path.stem.replace("_summary", "")
                try:
                    decrypted = crypto.decrypt_data(enc_path.read_text(encoding="utf-8"), self.encryption_key)
                    summary = json.loads(decrypted)
                except Exception as e:
                    logger.error("failed to decrypt/parse %s: %s", enc_path, e)
                    continue

                existing = db.get_session(session_id)
                if existing is not None:
                    # Last-Write-Wins on timestamp; cr-sqlite (when loaded, see
                    # storage.init_db) handles this natively on real CRDT tables.
                    # This is the plain-SQLite fallback merge policy.
                    incoming_ts = summary.get("created_at", "")
                    existing_ts = existing.get("updated_at") or existing.get("created_at") or ""
                    if incoming_ts and incoming_ts <= existing_ts:
                        conflicts += 1
                        continue
                    db.store_summary(session_id, summary)
                else:
                    db.store_summary(session_id, summary)
                files_changed += 1

        _update_device_metadata(self.repo_path, pending_changes=0)
        logger.info(
            "pull complete: files_changed=%d conflicts=%d", files_changed, conflicts
        )
        return {"direction": "pull", "files_changed": files_changed, "conflicts": conflicts}

    def sync(self, direction: str = "bidirectional") -> dict:
        """Orchestrate a full sync: pull, merge, push, rebuild ChromaDB.

        `direction` is one of "pull", "push", or "bidirectional".
        Errors from any stage are logged and re-raised after cleanup.
        """
        _setup_file_logging()
        result = {"pull": None, "push": None, "reindexed": 0}
        try:
            if direction in ("pull", "bidirectional"):
                result["pull"] = self.pull_from_github()

            if direction in ("push", "bidirectional"):
                result["push"] = self.push_to_github()

            if result["pull"] and result["pull"]["files_changed"] > 0:
                from src.embedder import reindex_all
                result["reindexed"] = reindex_all(db_path=self.db_path, chroma_path=self.chroma_path)

            logger.info("sync complete: direction=%s result=%s", direction, result)
            return result
        except Exception as e:
            logger.error("sync failed: direction=%s error=%s", direction, e)
            raise

    def daemon_loop(self, interval: int = DEFAULT_SYNC_INTERVAL_SECONDS, iterations: Optional[int] = None) -> None:
        """Run sync on a fixed interval, checking for local changes first.

        Exits silently (no network call) when there is nothing to push,
        but still pulls to catch changes from other devices.
        """
        _setup_file_logging()
        count = 0
        while iterations is None or count < iterations:
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
