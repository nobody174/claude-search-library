"""Official claude.ai Data Export import (Web Chat Import, see CHANGELOG.md).

Converts the ZIP/JSON a user downloads from claude.ai's own
Settings -> Export Data feature (Anthropic's `conversations.json` shape:
uuid/name/chat_messages[]/sender/text) into the per-session raw-export
JSON files collect_from_claude_ai() already watches.

Deliberately does NOT talk to claude.ai's API in any way — this is the
only sanctioned export path. ROADMAP.md's iOS chat capture entry found
that any automated access to claude.ai (unofficial scrapers, cookie-based
clients) violates Anthropic's Consumer Terms; this module only ever
reads a file the user downloaded through the official UI.
"""
from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _extract_message_text(message: dict) -> str:
    """Handle both the flat `text` field and the block-structured `content`
    field — the real export has used both across format versions."""
    text = message.get("text")
    if text:
        return text
    parts = []
    for block in message.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
            parts.append(block["text"])
    return "\n".join(parts)


def _convert_conversation(conversation: dict) -> Optional[dict]:
    """Convert one entry of the official export's conversations.json into
    the raw-export shape normalize_session() expects."""
    conv_id = conversation.get("uuid") or conversation.get("id")
    if not conv_id:
        return None

    messages = []
    for m in conversation.get("chat_messages") or conversation.get("messages") or []:
        sender = m.get("sender") or m.get("role")
        role = "assistant" if sender in ("assistant", "bot") else "user"
        text = _extract_message_text(m)
        if not text.strip():
            continue
        messages.append({
            "role": role,
            "content": text,
            "timestamp": m.get("created_at") or m.get("timestamp"),
        })

    if not messages:
        return None

    return {
        "id": conv_id,
        "title": conversation.get("name") or conversation.get("title") or "Untitled Session",
        "created_at": conversation.get("created_at"),
        "updated_at": conversation.get("updated_at"),
        "messages": messages,
    }


def _load_conversations(export_path: Path) -> list:
    """Read conversations.json contents from either a raw export ZIP or a
    bare JSON file (a single conversation object or a list of them)."""
    if export_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(export_path) as zf:
            candidates = [n for n in zf.namelist() if n.endswith("conversations.json")]
            if not candidates:
                raise ValueError(f"No conversations.json found inside {export_path}")
            with zf.open(candidates[0]) as f:
                data = json.load(f)
    else:
        with open(export_path, "r", encoding="utf-8") as f:
            data = json.load(f)

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ValueError(f"Unrecognized export format in {export_path}")
    return data


def import_official_export(export_path: str, output_dir: Optional[str] = None) -> dict:
    """Convert a claude.ai Data Export (ZIP or bare conversations.json) into
    one raw-export JSON file per conversation, written to output_dir
    (default: the same folder collect_from_claude_ai() watches).

    Returns {"converted": int, "skipped": int, "files": [str, ...]}.
    """
    path = Path(export_path)
    if not path.exists():
        raise FileNotFoundError(f"No such export file: {export_path}")

    if output_dir is None:
        output_dir = str(Path.home() / ".claude-search-library" / "data" / "raw_exports" / "claude-ai")
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    conversations = _load_conversations(path)

    files = []
    skipped = 0
    for conversation in conversations:
        converted = _convert_conversation(conversation)
        if converted is None:
            skipped += 1
            continue
        out_path = out_dir / f"{converted['id']}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(converted, f)
        files.append(str(out_path))

    return {"converted": len(files), "skipped": skipped, "files": files}
