#
# Claude Search Library
# Author:  nobody174
# Repo:    https://github.com/nobody174/claude-search-library
# Patreon: https://www.patreon.com/c/Nobody174
# License: MIT
# "It's never too late to give up!"
#

"""Cost reporting module for Claude Search Library.

Tracks API spend per session and produces monthly/quarterly reports.
Every summarization call in src/processor.py records its token usage
here via record_usage(). See CHANGELOG.md.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

# USD per million tokens, (input, output). Cache read/write tokens are
# billed at the same per-model input rate scaled by the standard Anthropic
# cache multipliers (0.1x for reads, 1.25x for 5-minute-TTL writes) rather
# than tracked as separate per-model rates.
PRICING_PER_MTOK = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-5": (5.00, 25.00),
}

CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25


def compute_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> float:
    """Compute the USD cost of one API call from its token usage.

    Falls back to Haiku 4.5 pricing (the default summarization model) for
    an unrecognized model string, rather than raising, so a model-string
    typo doesn't crash a processing batch over cost logging.
    """
    input_rate, output_rate = PRICING_PER_MTOK.get(model, PRICING_PER_MTOK["claude-haiku-4-5"])

    cost = input_tokens * input_rate / 1_000_000
    cost += output_tokens * output_rate / 1_000_000
    cost += cache_creation_input_tokens * input_rate * CACHE_WRITE_MULTIPLIER / 1_000_000
    cost += cache_read_input_tokens * input_rate * CACHE_READ_MULTIPLIER / 1_000_000
    return cost


def record_usage(db, session_id: Optional[str], model: str, usage: dict) -> float:
    """Compute and persist the cost of one API call. Returns the cost in USD.

    `usage` is expected to carry input_tokens/output_tokens and optionally
    cache_creation_input_tokens/cache_read_input_tokens (0 if absent).
    """
    input_tokens = usage.get("input_tokens", 0) or 0
    output_tokens = usage.get("output_tokens", 0) or 0
    cache_creation = usage.get("cache_creation_input_tokens", 0) or 0
    cache_read = usage.get("cache_read_input_tokens", 0) or 0

    cost = compute_cost(model, input_tokens, output_tokens, cache_creation, cache_read)

    db.log_api_cost(
        session_id=session_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_creation,
        cache_read_input_tokens=cache_read,
        cost_usd=cost,
        called_at=datetime.now(timezone.utc).isoformat(),
    )
    return cost


def month_range(month: str) -> tuple[str, str]:
    """Convert 'YYYY-MM' into an ISO [start, end) timestamp range."""
    start_dt = datetime.strptime(month, "%Y-%m").replace(tzinfo=timezone.utc)
    if start_dt.month == 12:
        end_dt = start_dt.replace(year=start_dt.year + 1, month=1)
    else:
        end_dt = start_dt.replace(month=start_dt.month + 1)
    return start_dt.isoformat(), end_dt.isoformat()


def quarter_range(quarter: str) -> tuple[str, str]:
    """Convert 'YYYY-QN' (N in 1-4) into an ISO [start, end) timestamp range."""
    year_str, q_str = quarter.split("-Q")
    year = int(year_str)
    q = int(q_str)
    if q not in (1, 2, 3, 4):
        raise ValueError(f"Invalid quarter: {quarter!r} (expected Q1-Q4)")
    start_month = (q - 1) * 3 + 1
    start_dt = datetime(year, start_month, 1, tzinfo=timezone.utc)
    if start_month == 10:
        end_dt = start_dt.replace(year=year + 1, month=1)
    else:
        end_dt = start_dt.replace(month=start_month + 3)
    return start_dt.isoformat(), end_dt.isoformat()


def get_report(db_path: Optional[str] = None, month: Optional[str] = None, quarter: Optional[str] = None) -> dict:
    """Build a cost report, optionally scoped to a month ('YYYY-MM') or
    quarter ('YYYY-QN'). With neither, reports all-time spend."""
    from src.storage import Storage

    start = end = None
    if month and quarter:
        raise ValueError("Pass only one of month or quarter, not both")
    if month:
        start, end = month_range(month)
    elif quarter:
        start, end = quarter_range(quarter)

    with Storage(db_path) as db:
        report = db.get_costs(start=start, end=end)

    report["period"] = month or quarter or "all-time"
    return report

# Built with assistance from Claude Code by Anthropic.
