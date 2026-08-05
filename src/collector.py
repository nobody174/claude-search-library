"""Data collection module for Claude Search Library.

Collects chat sessions from Claude.ai exports, the VS Code Claude extension,
Cowork, and a local watch folder, normalizing all of them into a common
schema (see SPEC.md -> Normalization Schema).
"""
from __future__ import annotations

import hashlib
import json
import logging
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_WATCH_INTERVAL_SECONDS = 300


def _content_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update((part or "").encode("utf-8"))
    return h.hexdigest()[:16]


def _approx_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def detect_device() -> str:
    """Best-effort guess at what kind of device this is running on."""
    system = platform.system().lower()
    if system == "darwin" and "iphone" in platform.platform().lower():
        return "phone"
    return "desktop"


def normalize_session(
    raw: dict,
    source: str,
    device: str,
    raw_path: str = "",
) -> dict:
    """Convert a loosely-structured chat export into the normalized schema."""
    messages_in = raw.get("messages") or []
    messages = []
    for m in messages_in:
        content = m.get("content", "") or ""
        messages.append(
            {
                "role": m.get("role", "user"),
                "content": content,
                "timestamp": m.get("timestamp") or raw.get("created_at") or "",
                "tokens_approx": m.get("tokens_approx", _approx_tokens(content)),
            }
        )

    created_at = raw.get("created_at") or (messages[0]["timestamp"] if messages else "")
    updated_at = raw.get("updated_at") or (messages[-1]["timestamp"] if messages else created_at)

    created_dt = _parse_iso(created_at)
    updated_dt = _parse_iso(updated_at)
    duration_seconds = 0
    if created_dt and updated_dt and updated_dt >= created_dt:
        duration_seconds = int((updated_dt - created_dt).total_seconds())

    user_count = sum(1 for m in messages if m["role"] == "user")
    assistant_count = sum(1 for m in messages if m["role"] == "assistant")

    session_id = raw.get("id") or _content_hash(source, raw_path, created_at, str(len(messages)))

    return {
        "id": str(session_id),
        "source": source,
        "title": raw.get("title") or "Untitled Session",
        "created_at": created_at,
        "updated_at": updated_at,
        "duration_seconds": duration_seconds,
        "message_count": len(messages),
        "user_message_count": user_count,
        "assistant_message_count": assistant_count,
        "messages": messages,
        "device": device,
        "tags": raw.get("tags", []),
        "raw_path": raw_path,
    }


def _load_json_files(folder: Path) -> list[tuple[dict, str]]:
    results = []
    if not folder.exists() or not folder.is_dir():
        return results
    for path in sorted(folder.glob("*.json")):
        if path.stem.endswith("_summary"):
            # Defense in depth: processor.py writes summaries to a separate
            # directory precisely to avoid this, but skip them here too in
            # case a collector folder ever ends up pointed at that
            # directory (e.g. a future --local-folder misconfiguration).
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Skipping unreadable export %s: %s", path, e)
            continue
        results.append((data, str(path)))
    return results


def collect_from_claude_ai(export_folder: str) -> list[dict]:
    """Read JSON files from a Claude.ai exports folder and normalize them."""
    folder = Path(export_folder)
    sessions = []
    for data, raw_path in _load_json_files(folder):
        try:
            sessions.append(normalize_session(data, "claude-ai", detect_device(), raw_path))
        except Exception as e:
            logger.warning("Failed to normalize %s: %s", raw_path, e)
    return sessions


def collect_from_vscode(extensions_path: Optional[str] = None) -> list[dict]:
    """Find the Claude VS Code extension's chat history and normalize it."""
    if extensions_path is None:
        extensions_path = str(Path.home() / ".vscode" / "extensions")

    ext_root = Path(extensions_path)
    sessions = []
    if not ext_root.exists():
        logger.info("VS Code extensions path not found: %s", ext_root)
        return sessions

    for ext_dir in ext_root.glob("anthropic.claude-vscode-*"):
        history_dir = ext_dir / "chat_history"
        for data, raw_path in _load_json_files(history_dir):
            try:
                sessions.append(normalize_session(data, "vscode", detect_device(), raw_path))
            except Exception as e:
                logger.warning("Failed to normalize %s: %s", raw_path, e)
    return sessions


def _default_claude_desktop_root() -> Optional[Path]:
    """Locate the Claude desktop app's (MSIX-packaged) Electron userData
    root. Shared by collect_from_claude_desktop() and collect_from_cowork()
    - see collect_from_claude_desktop()'s docstring for why this path
    (rather than the usual %APPDATA%\\Claude) is correct on this machine."""
    if platform.system().lower() != "windows":
        return None
    local_appdata = Path.home() / "AppData" / "Local"
    return (
        local_appdata / "Packages" / "Claude_pzs8sxrjxfjjc" / "LocalCache" / "Roaming" / "Claude"
    )


def _winlongpath(path: Path) -> Path:
    """Prefix an absolute Windows path with \\\\?\\ so pathlib/os calls bypass
    the classic 260-character MAX_PATH limit.

    Needed for Cowork session paths specifically: the real nested
    directory structure (local-agent-mode-sessions/<account>/<org>/
    local_<uuid>/.claude/projects/<sanitized-full-path-as-dirname>/) has
    been observed exceeding 440 characters, well past MAX_PATH. Without
    this prefix, iterdir()/glob() on such a path fail with a silent
    FileNotFoundError (not an obviously-relevant error - it looks like
    "the directory doesn't exist" even though it does) rather than any
    error naming the real cause. No-op on non-Windows or already-prefixed
    paths.
    """
    if platform.system().lower() != "windows":
        return path
    resolved = str(path.resolve())
    if resolved.startswith("\\\\?\\"):
        return path
    return Path("\\\\?\\" + resolved)


def collect_from_cowork(cowork_path: Optional[str] = None) -> list[dict]:
    """Collect Cowork (autonomous agent-mode) session transcripts from the
    Claude desktop app's local session store.

    Discovered 2026-08-04: each Cowork session runs a full local Claude
    Code instance in its own sandbox, which writes the exact same JSONL
    transcript format regular Claude Code uses
    (~/.claude/projects/<project>/<session>.jsonl) - just nested under the
    desktop app's own
    local-agent-mode-sessions/<account-id>/<org-id>/local_<session-uuid>/
    .claude/projects/ tree instead of the user's home directory. Reuses
    _convert_claude_code_transcript() unchanged for the actual parsing -
    no new wire format to reverse-engineer here, unlike
    collect_from_claude_desktop()'s IndexedDB/Snappy/V8 problem.

    Each local_<uuid> session directory has a sibling local_<uuid>.json
    metadata file one level up carrying the session's real title and
    createdAt (Unix ms) exactly as shown in the Cowork UI - preferred here
    over the transcript's own embedded ai-title line/timestamps, since
    it's the authoritative user-facing value.

    Real, confirmed limitation (not a bug): Cowork sessions are entirely
    absent from claude.ai's standard Settings -> Export Data feature - a
    real Cowork session (dated 2026-07-26, confirmed against this exact
    metadata file) was completely missing from a full account export
    covering that date range. This local session store is therefore not
    just an incremental supplement the way collect_from_claude_desktop()
    is - for Cowork specifically, it is currently the *only* way to
    recover this history at all.
    """
    if cowork_path is None:
        desktop_root = _default_claude_desktop_root()
        if desktop_root is None:
            return []
        root = desktop_root / "local-agent-mode-sessions"
    else:
        root = Path(cowork_path)

    sessions: list[dict] = []
    if not root.exists():
        return sessions

    export_dir = Path.home() / ".claude-search-library" / "data" / "raw_exports" / "cowork"
    export_dir.mkdir(parents=True, exist_ok=True)

    for meta_path in root.glob("**/local_*.json"):
        session_dir = _winlongpath(meta_path.parent / meta_path.stem)
        if not session_dir.is_dir():
            continue

        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to read Cowork session metadata %s: %s", meta_path, e)
            continue

        jsonl_paths = list(session_dir.glob(".claude/projects/*/*.jsonl"))
        if not jsonl_paths:
            continue

        try:
            raw = _convert_claude_code_transcript(jsonl_paths[0])
        except OSError as e:
            logger.warning("Failed to read Cowork transcript %s: %s", jsonl_paths[0], e)
            continue
        if raw is None:
            continue

        if meta.get("title"):
            raw["title"] = meta["title"]
        created_at_ms = meta.get("createdAt")
        if created_at_ms:
            raw["created_at"] = datetime.fromtimestamp(created_at_ms / 1000, tz=timezone.utc).isoformat()

        out_path = export_dir / f"{raw['id']}.json"
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(raw, f)
        except OSError as e:
            logger.warning("Failed to write converted Cowork transcript %s: %s", out_path, e)
            continue

        try:
            sessions.append(normalize_session(raw, "cowork", detect_device(), str(out_path)))
        except Exception as e:
            logger.warning("Failed to normalize Cowork session %s: %s", meta_path, e)

    return sessions


def _extract_text_content(content) -> str:
    """Flatten a Claude Code message's content into plain text.

    Claude Code transcript entries carry a list of typed blocks (text,
    thinking, tool_use, tool_result, ...); only text blocks are
    user-readable narrative, so tool/thinking blocks are dropped here
    rather than summarized.
    """
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            if text:
                parts.append(text)
    return "\n".join(parts)


def _convert_claude_code_transcript(jsonl_path: Path) -> Optional[dict]:
    """Convert one ~/.claude/projects/*/*.jsonl transcript into the same
    raw export shape normalize_session() expects from a claude.ai export
    (id/title/created_at/messages), skipping non-conversational lines
    (queue-operations, file-history snapshots, etc.) and turns with no
    text content (pure tool-use/thinking turns)."""
    session_id = None
    title = None
    messages = []

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type")
            if entry_type == "ai-title":
                title = entry.get("aiTitle")
                continue
            if entry_type not in ("user", "assistant"):
                continue

            message = entry.get("message") or {}
            role = message.get("role")
            text = _extract_text_content(message.get("content"))
            if not role or not text.strip():
                continue

            session_id = entry.get("sessionId") or session_id
            messages.append({"role": role, "content": text, "timestamp": entry.get("timestamp")})

    if not messages or not session_id:
        return None

    return {
        "id": session_id,
        "title": title or "Claude Code session",
        "created_at": messages[0]["timestamp"],
        "updated_at": messages[-1]["timestamp"],
        "messages": messages,
    }


def collect_from_claude_code(projects_path: Optional[str] = None) -> list[dict]:
    """Collect sessions from Claude Code's local transcript store
    (~/.claude/projects/<project>/<session_id>.jsonl).

    Each transcript is converted to the standard raw-export JSON shape
    and materialized under raw_exports/claude-code/ so it participates
    in the same on-disk-hash/dedup/export flow as every other source.
    """
    if projects_path is None:
        projects_path = str(Path.home() / ".claude" / "projects")

    root = Path(projects_path)
    sessions = []
    if not root.exists():
        return sessions

    export_dir = Path.home() / ".claude-search-library" / "data" / "raw_exports" / "claude-code"
    export_dir.mkdir(parents=True, exist_ok=True)

    for jsonl_path in root.glob("*/*.jsonl"):
        try:
            raw = _convert_claude_code_transcript(jsonl_path)
        except OSError as e:
            logger.warning("Failed to read %s: %s", jsonl_path, e)
            continue
        if raw is None:
            continue

        out_path = export_dir / f"{raw['id']}.json"
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(raw, f)
        except OSError as e:
            logger.warning("Failed to write converted transcript %s: %s", out_path, e)
            continue

        try:
            sessions.append(normalize_session(raw, "claude-code", detect_device(), str(out_path)))
        except Exception as e:
            logger.warning("Failed to normalize %s: %s", jsonl_path, e)

    return sessions


def _idb_ssv_decode(buf: bytes, blink_deserializer, raw_db, db_id: int, store_id: int, raw_key: bytes):
    """Decode one IndexedDB record value's Blink-wrapped SerializedScriptValue
    (SSV) payload into a Python object, using ccl_chromium_reader's V8/Blink
    deserializers directly.

    This exists instead of calling ccl_chromium_reader's own
    IndexedDb.read_record_precursor()/iterate_records() because those don't
    implement Chromium's "processing pseudo-version" wrapper used once a
    value gets large enough to compress: real Chromium IDB values start with
    `0xFF <wire-version-varint>`, but when the version equals
    `0x11` (17 decimal, `kRequiresProcessingSSVPseudoVersion` - a sentinel,
    not a real wire version) the *next* byte is a command, not payload:
    `0x01` = kReplaceWithBlob (externalized to a `.blob` file - handled
    separately by the library) or `0x02` = kCompressedWithSnappy (the rest
    of the buffer is a raw Snappy stream that decompresses to another,
    inner Blink-wrapped SSV). ccl_chromium_reader (as of the version
    installed here, see requirements.txt) has no branch for `0x02` at all -
    it hands the still-compressed bytes straight to the V8 deserializer,
    which fails immediately or silently misparses. See upstream issue
    https://github.com/cclgroupltd/ccl_chromium_reader/issues/44, which
    this function implements the fix from. Chromium compresses any IDB
    value once it crosses a size threshold, which is exactly the case for
    a claude.ai react-query cache holding real conversation histories, so
    this isn't an edge case for this collector - it's the common path.
    """
    from ccl_chromium_reader import ccl_chromium_indexeddb as idbmod
    from ccl_chromium_reader.serialization_formats import ccl_v8_value_deserializer
    import ccl_simplesnappy
    import io as _io

    if not buf or buf[0] != 0xFF:
        raise ValueError("Not a Blink-wrapped SSV (missing 0xFF tag)")

    pos = 1
    version, vraw = idbmod._le_varint_from_bytes(buf[pos:])
    pos += len(vraw)

    if version == 0x11:  # kRequiresProcessingSSVPseudoVersion
        command = buf[pos]
        pos += 1
        if command == 0x02:  # kCompressedWithSnappy
            decompressed = ccl_simplesnappy.decompress(_io.BytesIO(buf[pos:]))
            return _idb_ssv_decode(decompressed, blink_deserializer, raw_db, db_id, store_id, raw_key)
        if command == 0x01:  # kReplaceWithBlob
            blob_size, vraw2 = idbmod._le_varint_from_bytes(buf[pos:])
            pos += len(vraw2)
            blob_index, vraw3 = idbmod._le_varint_from_bytes(buf[pos:])
            blob_bytes = raw_db.get_blob(db_id, store_id, raw_key, blob_index).read()
            return _idb_ssv_decode(blob_bytes, blink_deserializer, raw_db, db_id, store_id, raw_key)
        raise ValueError(f"Unknown IDB value-wrapping command byte {command:#x}")

    # Genuine Blink wire version: a 13-byte trailer (tag + offset + length,
    # big-endian) follows once the version is new enough to carry one,
    # before the actual V8-serialized payload.
    if version >= 21:
        pos += 13

    obj_raw = _io.BytesIO(buf[pos:])
    deserializer = ccl_v8_value_deserializer.Deserializer(obj_raw, host_object_delegate=blink_deserializer.read)
    return deserializer.read()


def _extract_claude_desktop_content(content_blocks) -> str:
    """Flatten a claude.ai desktop-app message's content blocks into plain
    text, the same way _extract_text_content() does for Claude Code
    transcripts: only "text"-typed blocks are user-authored/user-readable
    narrative, "thinking" blocks are the model's internal reasoning and are
    dropped here."""
    if isinstance(content_blocks, str):
        return content_blocks
    parts = []
    for block in content_blocks or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            if text:
                parts.append(text)
    return "\n".join(parts)


def _convert_claude_desktop_tree(tree: dict) -> Optional[dict]:
    """Convert one decoded `chat_conversation_tree` react-query cache entry
    (claude.ai's own conversation-detail API response shape, as cached
    client-side) into the standard raw-export shape normalize_session()
    expects."""
    uuid = tree.get("uuid")
    chat_messages = tree.get("chat_messages")
    if not uuid or not chat_messages:
        return None

    messages = []
    for m in chat_messages:
        sender = m.get("sender")
        role = {"human": "user", "assistant": "assistant"}.get(sender, sender or "user")
        text = _extract_claude_desktop_content(m.get("content"))
        if not text.strip():
            continue
        messages.append({"role": role, "content": text, "timestamp": m.get("created_at")})

    if not messages:
        return None

    return {
        "id": uuid,
        "title": tree.get("name") or "Untitled conversation",
        "created_at": tree.get("created_at") or messages[0]["timestamp"],
        "updated_at": tree.get("updated_at") or messages[-1]["timestamp"],
        "messages": messages,
    }


def _default_claude_desktop_indexeddb_root() -> Optional[Path]:
    """Locate the Claude desktop app's IndexedDB directory (see
    _default_claude_desktop_root() for the shared userData root logic)."""
    root = _default_claude_desktop_root()
    return None if root is None else root / "IndexedDB"


def collect_from_claude_desktop(indexeddb_root: Optional[str] = None) -> list[dict]:
    """Collect real conversation history cached by the Claude desktop app
    (the claude.ai account, via the official Windows app) from its local
    IndexedDB store.

    The desktop app is an Electron/Chromium app. It uses IndexedDB
    (LevelDB-backed) as a client-side cache for its React Query data
    layer, including a "react-query-cache" entry holding dehydrated query
    results - among them `chat_conversation_tree` queries, which carry a
    conversation's full title + message history exactly as fetched from
    claude.ai's own API, just cached to disk for fast reloads/offline use.
    This reads that cache directly; it never talks to claude.ai's API
    itself (see CHANGELOG.md's "Claude desktop app chat capture"
    investigation for why that distinction matters and why the
    API-scraping approach ruled out for iOS capture, see ROADMAP.md,
    does not apply here).

    Important limitation: this only recovers conversations the user has
    actually *opened* in the desktop app while the query cache held them
    (and that haven't since been evicted) - not full account history the
    way the official Settings -> Export Data feature would give you. It's
    a real, useful, incremental source, not a replacement for occasional
    full-export catch-up (Web Chat Import, see CHANGELOG.md).

    The app holds a LevelDB single-writer lock while running, so this
    always copies the whole IndexedDB directory (+ its sibling .blob
    directory holding overflow/large values) to a temp location before
    reading anything, and never opens or writes to the live store.
    """
    if indexeddb_root is None:
        root = _default_claude_desktop_indexeddb_root()
    else:
        root = Path(indexeddb_root)

    sessions: list[dict] = []
    if root is None or not root.exists():
        logger.info("Claude desktop IndexedDB store not found (root=%s)", root)
        return sessions

    leveldb_dir = root / "https_claude.ai_0.indexeddb.leveldb"
    blob_dir = root / "https_claude.ai_0.indexeddb.blob"
    if not leveldb_dir.exists():
        logger.info("Claude desktop IndexedDB leveldb dir not found: %s", leveldb_dir)
        return sessions

    try:
        from ccl_chromium_reader.ccl_chromium_indexeddb import WrappedIndexDB
        from ccl_chromium_reader import ccl_chromium_indexeddb as idbmod
    except ImportError:
        logger.warning(
            "ccl_chromium_reader not installed; cannot read the Claude desktop "
            "IndexedDB store. Install with: pip install "
            "git+https://github.com/obsidianforensics/ccl_chrome_indexeddb.git"
        )
        return sessions

    import shutil
    import tempfile

    tmp_dir = Path(tempfile.mkdtemp(prefix="claude_desktop_idb_"))
    try:
        tmp_leveldb = tmp_dir / leveldb_dir.name
        shutil.copytree(leveldb_dir, tmp_leveldb)
        tmp_blob = None
        if blob_dir.exists():
            tmp_blob = tmp_dir / blob_dir.name
            shutil.copytree(blob_dir, tmp_blob)

        try:
            with WrappedIndexDB(tmp_leveldb, tmp_blob) as db:
                if "keyval-store" not in db:
                    logger.info("Claude desktop IndexedDB has no 'keyval-store' database")
                    return sessions
                wdb = db["keyval-store"]
                if "keyval" not in wdb.object_store_names:
                    logger.info("Claude desktop 'keyval-store' has no 'keyval' object store")
                    return sessions
                store = wdb["keyval"]
                db_id = store._dbid_no
                store_id = store._obj_store_id
                raw_db = store._raw_db

                blink_deserializer = idbmod.ccl_blink_value_deserializer.BlinkV8Deserializer()
                prefix = raw_db.make_prefix(db_id, store_id, 1)

                # LevelDB is append-only: every overwrite of the
                # "react-query-cache" key leaves the old physical record in
                # place until compaction runs, so an uncompacted dump can
                # hold thousands of superseded versions of the same logical
                # key. We only want the current one - and decoding the
                # stale ones isn't just wasted work, it's *pathologically
                # slow* wasted work: superseded "kReplaceWithBlob" records
                # point at blob files that later blob-GC has already
                # deleted, and get_blob()'s FileNotFoundError path is slow
                # enough (~0.6s observed) that a real profile with a few
                # thousand stale records turns this into a de facto hang
                # (30+ min) instead of the sub-second job it should be.
                # record.seq is the LevelDB write sequence number, so
                # picking the max-seq record per physical key before ever
                # calling the decoder fixes both correctness (stale writes
                # never should have been read as current) and performance.
                latest_by_key: dict[bytes, object] = {}
                for record in raw_db._fetched_records:
                    if not record.key.startswith(prefix):
                        continue
                    if record.state != idbmod.ccl_leveldb.KeyState.Live:
                        continue
                    if not record.value:
                        continue
                    key = idbmod.IdbKey(record.key[len(prefix):])
                    if key.value != "react-query-cache":
                        continue
                    existing = latest_by_key.get(record.key)
                    if existing is None or record.seq > existing.seq:
                        latest_by_key[record.key] = record

                trees: dict[str, dict] = {}
                for record in latest_by_key.values():
                    key = idbmod.IdbKey(record.key[len(prefix):])
                    value_version, varint_raw = idbmod._le_varint_from_bytes(record.value)
                    buf = record.value[len(varint_raw):]
                    try:
                        value = _idb_ssv_decode(buf, blink_deserializer, raw_db, db_id, store_id, key.raw_key)
                    except Exception as e:
                        logger.debug("Skipping undecodable react-query-cache record: %s", e)
                        continue

                    if not isinstance(value, dict):
                        continue
                    queries = (value.get("clientState") or {}).get("queries") or []
                    for q in queries:
                        if not isinstance(q, dict):
                            continue
                        query_key = q.get("queryKey")
                        if not query_key or query_key[0] != "chat_conversation_tree":
                            continue
                        tree = (q.get("state") or {}).get("data")
                        if not isinstance(tree, dict) or not tree.get("uuid"):
                            continue
                        existing = trees.get(tree["uuid"])
                        if existing is None or len(tree.get("chat_messages") or []) >= len(
                            existing.get("chat_messages") or []
                        ):
                            trees[tree["uuid"]] = tree
        except Exception as e:
            logger.warning("Failed to read Claude desktop IndexedDB store: %s", e)
            return sessions
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    export_dir = Path.home() / ".claude-search-library" / "data" / "raw_exports" / "claude-desktop"
    export_dir.mkdir(parents=True, exist_ok=True)

    for uuid, tree in trees.items():
        raw = _convert_claude_desktop_tree(tree)
        if raw is None:
            continue

        out_path = export_dir / f"{raw['id']}.json"
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(raw, f)
        except OSError as e:
            logger.warning("Failed to write converted conversation %s: %s", out_path, e)
            continue

        try:
            sessions.append(normalize_session(raw, "claude-desktop", detect_device(), str(out_path)))
        except Exception as e:
            logger.warning("Failed to normalize claude-desktop conversation %s: %s", uuid, e)

    return sessions


def collect_from_local(folder_path: str) -> list[dict]:
    """Import any JSON files sitting in a local watch folder."""
    folder = Path(folder_path)
    sessions = []
    for data, raw_path in _load_json_files(folder):
        try:
            sessions.append(normalize_session(data, "local", detect_device(), raw_path))
        except Exception as e:
            logger.warning("Failed to normalize %s: %s", raw_path, e)
    return sessions


def _session_to_storage_dict(session: dict) -> dict:
    """Map a normalize_session() dict onto Storage.SESSION_COLUMNS.

    normalize_session() produces a richer in-memory schema (messages, tags,
    raw_path) than the sessions table stores directly; this adapts field
    names (raw_path -> raw_file_path) and fills in the columns Storage
    expects for insert_session().
    """
    return {
        "id": session["id"],
        "source": session["source"],
        "device": session["device"],
        "title": session["title"],
        "created_at": session["created_at"],
        "updated_at": session["updated_at"],
        "duration_seconds": session["duration_seconds"],
        "message_count": session["message_count"],
        "user_message_count": session["user_message_count"],
        "assistant_message_count": session["assistant_message_count"],
        "raw_file_path": session.get("raw_path") or None,
        "summary_file_path": None,
        "processed_at": None,
        "status": "new",
        "review_reason": None,
        "synced_at": None,
        "sync_version": 1,
    }


def _load_raw_export_for_hash(session: dict) -> Optional[dict]:
    """Re-read a session's original export file for content hashing.

    compute_session_hash() must see the same bytes verify_archive() will
    later see when it re-reads and re-hashes the file from disk (see the
    docstring on compute_session_hash in storage.py) — so this re-parses
    the raw file rather than reconstructing an approximation from the
    already-normalized session dict, which previously caused hashes to
    mismatch (normalize_session() adds tokens_approx and backfills
    timestamp, neither of which exist in the original file).

    Returns None if there's no raw_path recorded or the file can't be
    read, in which case the caller falls back to hashing the normalized
    session — internally consistent, but won't match a later re-read.
    """
    raw_path = session.get("raw_path")
    if not raw_path:
        return None
    try:
        with open(raw_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def collect_all(
    claude_ai_folder: Optional[str] = None,
    vscode_extensions_path: Optional[str] = None,
    cowork_path: Optional[str] = None,
    local_folder: Optional[str] = None,
    db_path: Optional[str] = None,
) -> dict:
    """Run all collectors, persist new sessions to storage, and return a
    summary of results.

    Errors in one collector do not prevent the others from running.
    Sessions are deduplicated by content hash via
    Storage.store_session_with_hash() — re-collecting the same conversation
    (even under a different id or from a different source folder) is a
    no-op rather than a duplicate row.
    """
    from src.storage import Storage  # local import: avoids a hard dependency for callers that only normalize

    base = Path.home() / ".claude-search-library" / "data" / "raw_exports"
    claude_ai_folder = claude_ai_folder or str(base / "claude-ai")
    local_folder = local_folder or str(base / "local")

    collectors = {
        "claude-ai": (collect_from_claude_ai, claude_ai_folder),
        "vscode": (collect_from_vscode, vscode_extensions_path),
        "cowork": (collect_from_cowork, cowork_path),
        "local": (collect_from_local, local_folder),
    }

    all_sessions: list[dict] = []
    errors = 0

    for name, (func, arg) in collectors.items():
        try:
            sessions = func(arg)
            all_sessions.extend(sessions)
        except Exception as e:
            logger.error("Collector '%s' failed: %s", name, e)
            errors += 1

    seen_ids = set()
    deduped_sessions = []
    for s in all_sessions:
        if s["id"] not in seen_ids:
            seen_ids.add(s["id"])
            deduped_sessions.append(s)

    new_count = 0
    with Storage(db_path) as db:
        for session in deduped_sessions:
            try:
                hash_source = _load_raw_export_for_hash(session)
                result = db.store_session_with_hash(
                    _session_to_storage_dict(session), hash_source=hash_source
                )
                if result["status"] == "inserted":
                    new_count += 1
            except Exception as e:
                logger.error("Failed to store session %s: %s", session.get("id"), e)
                errors += 1

    return {
        "new": new_count,
        "errors": errors,
        "total": len(all_sessions),
    }


def watch(interval: int = DEFAULT_WATCH_INTERVAL_SECONDS, iterations: Optional[int] = None) -> None:
    """Run collect_all() on a fixed interval, forever (or `iterations` times)."""
    count = 0
    while iterations is None or count < iterations:
        result = collect_all()
        logger.info(
            "Collection run: %d new, %d errors, %d total",
            result["new"], result["errors"], result["total"],
        )
        count += 1
        if iterations is None or count < iterations:
            time.sleep(interval)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Claude Search Library collector")
    parser.add_argument("--watch", action="store_true", help="Run collection on a recurring interval")
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_WATCH_INTERVAL_SECONDS,
        help="Seconds between collection runs when --watch is set (default: 300)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.watch:
        watch(interval=args.interval)
    else:
        result = collect_all()
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
