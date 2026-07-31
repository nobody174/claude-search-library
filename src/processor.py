"""Processing & summarization module for Claude Search Library.

Summarizes chat sessions using the Claude API, batching requests to respect
rate limits, retrying transient failures with backoff, and writing sidecar
summary JSON files next to each raw chat export.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)

LOG_PATH = Path.home() / ".claude-search-library" / "logs" / "processing.log"
NEEDS_REVIEW_DIR = Path.home() / ".claude-search-library" / "needs_review"

MODEL = "claude-opus-5"
MAX_INPUT_TOKENS = 16000
MAX_CALLS_PER_MINUTE = 10
REQUEST_TIMEOUT_SECONDS = 30
MAX_JSON_RETRIES = 3
MAX_BACKOFF_RETRIES = 3

SYSTEM_PROMPT_TEMPLATE = """Analyze this chat session. Respond ONLY with valid JSON (no markdown, no preamble).

User and Claude worked on: {description}

Respond with exactly this structure:
{{
    "session_tldr": "One sentence: what was accomplished",
    "learnings": [
        "Key takeaway 1",
        "Key takeaway 2"
    ],
    "patterns": [
        "Reusable workflow 1",
        "Reusable workflow 2"
    ],
    "tags": ["tag1", "tag2"],
    "mentioned_tools": ["Tool1", "Tool2"],
    "mentioned_languages": ["Python", "TypeScript"],
    "mentioned_frameworks": ["Phaser 3", "NeoForge"],
    "estimated_effort_minutes": 45,
    "topic_categories": ["minecraft-modding", "debugging"],
    "confidence_score": 0.92
}}"""

REQUIRED_SUMMARY_FIELDS = {
    "session_tldr",
    "learnings",
    "patterns",
    "tags",
    "mentioned_tools",
    "mentioned_languages",
    "mentioned_frameworks",
    "estimated_effort_minutes",
    "topic_categories",
    "confidence_score",
}


def _setup_file_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not any(isinstance(h, logging.FileHandler) and h.baseFilename == str(LOG_PATH) for h in logger.handlers):
        handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)


def _log_event(session_id: str, status: str, error: Optional[str] = None) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    if error:
        logger.info("session_id=%s status=%s error=%s", session_id, status, error)
    else:
        logger.info("session_id=%s status=%s timestamp=%s", session_id, status, timestamp)


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _build_narrative(chat_dict: dict) -> str:
    lines = []
    for m in chat_dict.get("messages", []):
        role = m.get("role", "user")
        content = m.get("content", "")
        lines.append(f"[{role}] {content}")
    return "\n\n".join(lines)


def _truncate_to_token_limit(text: str, max_tokens: int) -> str:
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[...truncated...]"


def _extract_description(chat_dict: dict) -> str:
    return chat_dict.get("title") or "an unspecified task"


def _parse_summary_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[: -3]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def _validate_summary_schema(summary: dict) -> bool:
    return REQUIRED_SUMMARY_FIELDS.issubset(summary.keys())


def summarize_chat(chat_dict: dict, api_key: str) -> dict:
    """Summarize a single chat session using the Claude API.

    Truncates the conversation to ~16k input tokens, calls Claude with the
    session-analysis system prompt, and returns the parsed summary dict.
    Retries up to 3 times on JSON parse errors; raises on schema mismatch
    or exhausted retries.
    """
    _setup_file_logging()
    session_id = chat_dict.get("id", "unknown")

    narrative = _build_narrative(chat_dict)
    narrative = _truncate_to_token_limit(narrative, MAX_INPUT_TOKENS)
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(description=_extract_description(chat_dict))

    client = anthropic.Anthropic(api_key=api_key)

    last_error: Optional[Exception] = None
    for attempt in range(1, MAX_JSON_RETRIES + 1):
        try:
            response = client.with_options(timeout=REQUEST_TIMEOUT_SECONDS).messages.create(
                model=MODEL,
                max_tokens=2048,
                system=system_prompt,
                messages=[{"role": "user", "content": narrative}],
            )
        except anthropic.APITimeoutError as e:
            _log_event(session_id, "timeout", str(e))
            raise
        except anthropic.RateLimitError as e:
            _log_event(session_id, "rate_limited", str(e))
            raise
        except anthropic.APIStatusError as e:
            _log_event(session_id, "api_error", str(e))
            raise

        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            summary = _parse_summary_json(text)
        except json.JSONDecodeError as e:
            last_error = e
            _log_event(session_id, f"json_parse_retry_{attempt}", str(e))
            continue

        if not _validate_summary_schema(summary):
            _log_event(session_id, "invalid_schema", f"missing fields: {REQUIRED_SUMMARY_FIELDS - summary.keys()}")
            _save_needs_review(chat_dict, summary)
            raise ValueError(f"Summary for session {session_id} failed schema validation")

        _log_event(session_id, "success")
        return summary

    _log_event(session_id, "failed", str(last_error))
    raise ValueError(f"Failed to parse summary JSON for session {session_id} after {MAX_JSON_RETRIES} attempts") from last_error


def _save_needs_review(chat_dict: dict, partial_summary: dict) -> None:
    NEEDS_REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    session_id = chat_dict.get("id", "unknown")
    path = NEEDS_REVIEW_DIR / f"{session_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"chat": chat_dict, "partial_summary": partial_summary}, f, indent=2)


def _save_summary_sidecar(raw_path: str, summary: dict) -> str:
    raw = Path(raw_path)
    sidecar_path = raw.with_name(f"{raw.stem}_summary.json")
    with open(sidecar_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    return str(sidecar_path)


def _load_session(session_id: str, sessions_dir: Path) -> Optional[dict]:
    for path in sessions_dir.glob("*.json"):
        if path.stem.endswith("_summary"):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("id") == session_id:
            data["_raw_path"] = str(path)
            return data
    return None


def process_batch(
    session_ids: list,
    api_key: str,
    batch_size: int = 10,
    sessions_dir: Optional[str] = None,
) -> dict:
    """Process a batch of sessions, respecting the 10 calls/minute rate limit.

    Looks up each session's raw JSON in `sessions_dir`, summarizes it, and
    writes the sidecar summary file. Applies exponential backoff on
    transient (timeout/rate-limit/server) failures, up to 3 retries per
    session. Returns a per-session result mapping.
    """
    _setup_file_logging()
    sessions_dir_path = Path(sessions_dir) if sessions_dir else (
        Path.home() / ".claude-search-library" / "raw_chats"
    )

    results = {"succeeded": [], "failed": [], "needs_review": []}
    calls_this_minute = 0
    minute_start = time.monotonic()

    for i in range(0, len(session_ids), batch_size):
        batch = session_ids[i : i + batch_size]
        for session_id in batch:
            if calls_this_minute >= MAX_CALLS_PER_MINUTE:
                elapsed = time.monotonic() - minute_start
                if elapsed < 60:
                    time.sleep(60 - elapsed)
                calls_this_minute = 0
                minute_start = time.monotonic()

            chat_dict = _load_session(session_id, sessions_dir_path)
            if chat_dict is None:
                _log_event(session_id, "not_found")
                results["failed"].append(session_id)
                continue

            raw_path = chat_dict.pop("_raw_path")
            success = _summarize_with_backoff(chat_dict, api_key, raw_path, results)
            calls_this_minute += 1
            if success:
                results["succeeded"].append(session_id)

    return results


def _summarize_with_backoff(chat_dict: dict, api_key: str, raw_path: str, results: dict) -> bool:
    session_id = chat_dict.get("id", "unknown")
    delay = 1.0
    for attempt in range(1, MAX_BACKOFF_RETRIES + 1):
        try:
            summary = summarize_chat(chat_dict, api_key)
            _save_summary_sidecar(raw_path, summary)
            return True
        except anthropic.APITimeoutError:
            _log_event(session_id, "timeout_skip")
            return False
        except ValueError:
            results["needs_review"].append(session_id)
            return False
        except (anthropic.RateLimitError, anthropic.APIStatusError) as e:
            if attempt == MAX_BACKOFF_RETRIES:
                _log_event(session_id, "backoff_exhausted", str(e))
                results["failed"].append(session_id)
                return False
            _log_event(session_id, f"backoff_retry_{attempt}", str(e))
            time.sleep(delay)
            delay *= 2
    return False
