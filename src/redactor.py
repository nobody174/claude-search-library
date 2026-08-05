#
# Claude Search Library
# Author:  nobody174
# Repo:    https://github.com/nobody174/claude-search-library
# Patreon: https://www.patreon.com/c/Nobody174
# License: MIT
# "It's never too late to give up!"
#

"""Redaction & privacy module for Claude Search Library.

Masks sensitive data (API keys, tokens, emails, IPs, etc.) in session
summaries before they are indexed, logs every redaction to both a flat
log file and a SQLite audit table, and flags sessions with excessive
redactions for manual review.
"""
from __future__ import annotations

import copy
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.storage import DEFAULT_DB_PATH as DB_PATH

logger = logging.getLogger(__name__)

LOG_PATH = Path.home() / ".claude-search-library" / "logs" / "redaction.log"

REVIEW_THRESHOLD = 3

# Ordered by confidence, highest first, so the most specific/certain patterns
# claim a match before a looser one (e.g. email) could apply to it.
REDACTION_PATTERNS = [
    ("github_token", re.compile(r"ghp_[a-zA-Z0-9]{36}"), "[GH_TOKEN_REDACTED]", 0.99),
    ("aws_key", re.compile(r"AKIA[0-9A-Z]{16}"), "[AWS_KEY_REDACTED]", 0.99),
    ("discord_token", re.compile(r"[MN][a-zA-Z\d]{23}\.[a-zA-Z\d-]{6}\.[a-zA-Z\d_-]{27}"), "[DISCORD_TOKEN_REDACTED]", 0.95),
    ("api_key", re.compile(r"api_?key.{0,40}?[a-zA-Z0-9]{20,}", re.IGNORECASE), "[API_KEY_REDACTED]", 0.9),
    ("patreon_link", re.compile(r"patreon\.com/[^\s]+", re.IGNORECASE), "[PATREON_LINK]", 0.85),
    ("email", re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "[EMAIL_REDACTED]", 0.8),
    ("ip_address", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[IP_REDACTED]", 0.7),
]


def _setup_file_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not any(isinstance(h, logging.FileHandler) and h.baseFilename == str(LOG_PATH) for h in logger.handlers):
        handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)


def _mask(value: str) -> str:
    """Mask a matched secret for logging: keep a short prefix, redact the rest."""
    if len(value) <= 6:
        return "*" * len(value)
    return value[:3] + "*" * (len(value) - 6) + value[-3:]


def _write_redaction_log(events: list, db_path: Optional[str] = None) -> None:
    """Append redaction events to the `redaction_log` table.

    Uses storage.init_db() rather than hand-rolling a CREATE TABLE here -
    this module used to define its own copy of the redaction_log schema,
    independent of storage.py's canonical one. Two sources of truth for
    one table's shape is exactly how schema drift happens; there's only
    one now.
    """
    if not events:
        return
    from src.storage import init_db

    path = str(Path(db_path)) if db_path else str(DB_PATH)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = init_db(path)
    try:
        conn.executemany(
            """
            INSERT INTO redaction_log
                (session_id, redaction_type, original_value, redacted_value,
                 confidence_score, redacted_at, manually_reviewed)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    e["session_id"],
                    e["redaction_type"],
                    e["original_value"],
                    e["redacted_value"],
                    e["confidence_score"],
                    e["redacted_at"],
                    e["manually_reviewed"],
                )
                for e in events
            ],
        )
        conn.commit()
    finally:
        conn.close()


def _redact_text(text: str, session_id: str) -> tuple[str, list]:
    """Apply all patterns to a single string, returning (redacted_text, events)."""
    events = []
    for redaction_type, pattern, placeholder, confidence in REDACTION_PATTERNS:
        def _replace(match: re.Match, _type=redaction_type, _placeholder=placeholder, _confidence=confidence) -> str:
            original = match.group(0)
            events.append(
                {
                    "session_id": session_id,
                    "redaction_type": _type,
                    "original_value": _mask(original),
                    "redacted_value": _placeholder,
                    "confidence_score": _confidence,
                    "redacted_at": datetime.now(timezone.utc).isoformat(),
                    "manually_reviewed": 0,
                }
            )
            return _placeholder

        text = pattern.sub(_replace, text)
    return text, events


def _redact_value(value, session_id: str) -> tuple[object, list]:
    if isinstance(value, str):
        return _redact_text(value, session_id)
    if isinstance(value, list):
        events = []
        redacted_list = []
        for item in value:
            redacted_item, item_events = _redact_value(item, session_id)
            redacted_list.append(redacted_item)
            events.extend(item_events)
        return redacted_list, events
    if isinstance(value, dict):
        events = []
        redacted_dict = {}
        for k, v in value.items():
            redacted_v, v_events = _redact_value(v, session_id)
            redacted_dict[k] = redacted_v
            events.extend(v_events)
        return redacted_dict, events
    return value, []


def redact_summary(summary_dict: dict, session_id: str, db_path: Optional[str] = None) -> tuple[dict, list]:
    """Redact sensitive data from a summary dict.

    Walks every string field (recursively through lists/dicts), applies the
    redaction patterns in confidence order, and returns the redacted summary
    alongside the list of redaction events. Sessions with more than
    REVIEW_THRESHOLD redactions get `needs_review: True` set on the returned
    summary. All events are logged to the flat log file and the SQLite
    `redaction_log` table.
    """
    _setup_file_logging()

    redacted_summary, events = _redact_value(copy.deepcopy(summary_dict), session_id)

    if len(events) > REVIEW_THRESHOLD:
        redacted_summary["needs_review"] = True
        redacted_summary["review_reason"] = f"{len(events)} redactions detected (threshold: {REVIEW_THRESHOLD})"
        logger.info(
            "session_id=%s status=needs_review redaction_count=%d",
            session_id, len(events),
        )

    for e in events:
        logger.info(
            "session_id=%s type=%s confidence=%.2f masked_value=%s",
            e["session_id"], e["redaction_type"], e["confidence_score"], e["original_value"],
        )

    _write_redaction_log(events, db_path=db_path)

    return redacted_summary, events

# Built with assistance from Claude Code by Anthropic.
