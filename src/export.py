"""Markdown export module for Claude Search Library.

Renders a session (raw messages, when available on disk) plus its stored
summary as a single shareable .md file. See ROADMAP.md #3.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from src.storage import Storage

logger = logging.getLogger(__name__)

DEFAULT_EXPORT_DIR = Path.home() / ".claude-search-library" / "exports"


def _load_messages(session: dict) -> list:
    """Best-effort read of the session's raw messages from its export file
    on disk. Returns an empty list if the file is missing or unreadable —
    export still proceeds with the summary alone."""
    raw_path = session.get("raw_file_path")
    if not raw_path:
        return []
    try:
        with open(raw_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Could not read raw export %s for markdown export: %s", raw_path, e)
        return []
    return data.get("messages") or []


def _render_summary(summary: dict) -> list[str]:
    lines = ["## Summary", ""]
    if summary.get("tldr"):
        lines += [f"**TL;DR:** {summary['tldr']}", ""]

    def _list_section(title: str, key: str) -> None:
        items = summary.get(key)
        if items:
            lines.append(f"**{title}:**")
            lines.extend(f"- {item}" for item in items)
            lines.append("")

    _list_section("Learnings", "learnings")
    _list_section("Patterns", "patterns")
    _list_section("Tags", "tags")

    if summary.get("topic_categories"):
        lines += [f"**Topics:** {', '.join(summary['topic_categories'])}", ""]

    return lines


def session_to_markdown(session: dict, summary: Optional[dict]) -> str:
    """Render a session (+ optional summary) as a Markdown document."""
    lines = [f"# {session.get('title') or '(untitled)'}", ""]
    lines += [
        f"- **Session ID:** {session['id']}",
        f"- **Source:** {session.get('source')} ({session.get('device')})",
        f"- **Created:** {session.get('created_at')}",
        f"- **Messages:** {session.get('message_count')}",
        "",
    ]

    if summary:
        lines += _render_summary(summary)

    messages = _load_messages(session)
    if messages:
        lines += ["## Conversation", ""]
        for m in messages:
            role = m.get("role", "user").capitalize()
            content = m.get("content", "") or ""
            lines += [f"### {role}", "", content, ""]
    else:
        lines += ["*Raw conversation text is unavailable (export file not found).*", ""]

    return "\n".join(lines)


def export_session(session_id: str, output_path: Optional[str] = None, db_path: Optional[str] = None) -> str:
    """Export a single session as a Markdown file. Returns the written path."""
    with Storage(db_path) as db:
        session = db.get_session(session_id)
        if session is None:
            raise ValueError(f"No session found with id {session_id}")
        summary = db.get_summary(session_id)

    markdown = session_to_markdown(session, summary)

    if output_path is None:
        DEFAULT_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = str(DEFAULT_EXPORT_DIR / f"{session_id}.md")
    else:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    return output_path
