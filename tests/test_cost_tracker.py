import pytest

from src import cost_tracker
from src.storage import Storage


def _sample_session(session_id: str) -> dict:
    return {
        "id": session_id, "source": "claude-ai", "device": "desktop", "title": "t",
        "created_at": "2026-07-31T14:22:00+00:00", "updated_at": "2026-07-31T14:22:00+00:00",
        "duration_seconds": 0, "message_count": 1, "user_message_count": 1,
        "assistant_message_count": 0, "raw_file_path": None, "summary_file_path": None,
        "content_hash": session_id, "processed_at": None, "status": "new",
        "review_reason": None, "synced_at": None, "sync_version": 1,
    }


def test_compute_cost_haiku():
    # 1000 input tokens @ $1/MTok + 1000 output tokens @ $5/MTok
    cost = cost_tracker.compute_cost("claude-haiku-4-5", input_tokens=1000, output_tokens=1000)
    assert cost == pytest.approx(0.001 + 0.005)


def test_compute_cost_unknown_model_falls_back_to_haiku():
    cost = cost_tracker.compute_cost("some-future-model", input_tokens=1000, output_tokens=1000)
    assert cost == pytest.approx(0.001 + 0.005)


def test_compute_cost_includes_cache_tokens():
    cost = cost_tracker.compute_cost(
        "claude-haiku-4-5",
        input_tokens=0,
        output_tokens=0,
        cache_creation_input_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
    )
    # cache write: 1.25x input rate; cache read: 0.1x input rate
    assert cost == pytest.approx(1.25 + 0.1)


def test_month_range():
    start, end = cost_tracker.month_range("2026-08")
    assert start.startswith("2026-08-01")
    assert end.startswith("2026-09-01")


def test_month_range_december_rolls_to_next_year():
    start, end = cost_tracker.month_range("2026-12")
    assert start.startswith("2026-12-01")
    assert end.startswith("2027-01-01")


def test_quarter_range():
    start, end = cost_tracker.quarter_range("2026-Q3")
    assert start.startswith("2026-07-01")
    assert end.startswith("2026-10-01")


def test_quarter_range_q4_rolls_to_next_year():
    start, end = cost_tracker.quarter_range("2026-Q4")
    assert start.startswith("2026-10-01")
    assert end.startswith("2027-01-01")


def test_quarter_range_rejects_invalid_quarter():
    with pytest.raises(ValueError):
        cost_tracker.quarter_range("2026-Q5")


def test_record_usage_persists_and_returns_cost():
    with Storage(":memory:") as db:
        db.insert_session(_sample_session("sess-1"))
        cost = cost_tracker.record_usage(
            db, "sess-1", "claude-haiku-4-5",
            {"input_tokens": 1000, "output_tokens": 1000},
        )
        assert cost == pytest.approx(0.006)

        report = db.get_costs()
        assert report["calls"] == 1
        assert report["total_cost_usd"] == pytest.approx(0.006)
        assert report["by_model"]["claude-haiku-4-5"]["calls"] == 1


def test_get_costs_filters_by_date_range():
    with Storage(":memory:") as db:
        db.insert_session(_sample_session("sess-1"))
        db.insert_session(_sample_session("sess-2"))
        db.log_api_cost(
            "sess-1", "claude-haiku-4-5", input_tokens=100, output_tokens=100,
            cost_usd=0.001, called_at="2026-07-15T00:00:00+00:00",
        )
        db.log_api_cost(
            "sess-2", "claude-haiku-4-5", input_tokens=200, output_tokens=200,
            cost_usd=0.002, called_at="2026-08-15T00:00:00+00:00",
        )

        report = db.get_costs(start="2026-08-01T00:00:00+00:00", end="2026-09-01T00:00:00+00:00")
        assert report["calls"] == 1
        assert report["total_cost_usd"] == pytest.approx(0.002)


def test_get_report_scoped_to_month(tmp_path):
    db_path = str(tmp_path / "test.db")
    with Storage(db_path) as db:
        db.insert_session(_sample_session("sess-1"))
        db.insert_session(_sample_session("sess-2"))
        db.log_api_cost(
            "sess-1", "claude-haiku-4-5", input_tokens=100, output_tokens=100,
            cost_usd=0.001, called_at="2026-08-10T00:00:00+00:00",
        )
        db.log_api_cost(
            "sess-2", "claude-haiku-4-5", input_tokens=100, output_tokens=100,
            cost_usd=0.001, called_at="2026-09-10T00:00:00+00:00",
        )

    report = cost_tracker.get_report(db_path=db_path, month="2026-08")
    assert report["calls"] == 1
    assert report["period"] == "2026-08"
