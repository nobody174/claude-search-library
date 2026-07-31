import sqlite3

import pytest

from src import redactor


@pytest.fixture(autouse=True)
def redirect_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(redactor, "LOG_PATH", tmp_path / "redaction.log")
    monkeypatch.setattr(redactor, "DB_PATH", tmp_path / "claude_search.db")
    redactor.logger.handlers.clear()
    yield


def test_redact_github_token():
    text = f"here is my token ghp_{'a' * 36} for the repo"
    redacted, events = redactor.redact_summary({"session_tldr": text}, "s1")
    assert "[GH_TOKEN_REDACTED]" in redacted["session_tldr"]
    assert len(events) == 1
    assert events[0]["redaction_type"] == "github_token"


def test_redact_aws_key():
    text = "export AWS_ACCESS_KEY_ID=AKIAABCDEFGHIJKLMNOP"
    redacted, events = redactor.redact_summary({"session_tldr": text}, "s2")
    assert "[AWS_KEY_REDACTED]" in redacted["session_tldr"]
    assert events[0]["redaction_type"] == "aws_key"


def test_redact_api_key_generic():
    text = "set api_key=sk-fake1234567890abcdefghijklmno in .env"
    redacted, events = redactor.redact_summary({"session_tldr": text}, "s3")
    assert "[API_KEY_REDACTED]" in redacted["session_tldr"]
    assert events[0]["redaction_type"] == "api_key"


def test_redact_email():
    redacted, events = redactor.redact_summary({"tags": ["contact me at fake.user@example.com"]}, "s4")
    assert "[EMAIL_REDACTED]" in redacted["tags"][0]
    assert events[0]["redaction_type"] == "email"


def test_redact_ip_address():
    redacted, events = redactor.redact_summary({"session_tldr": "server at 192.168.1.42 failed"}, "s5")
    assert "[IP_REDACTED]" in redacted["session_tldr"]
    assert events[0]["redaction_type"] == "ip_address"


def test_redact_patreon_link():
    redacted, events = redactor.redact_summary({"session_tldr": "support at patreon.com/fakecreator"}, "s6")
    assert "[PATREON_LINK]" in redacted["session_tldr"]
    assert events[0]["redaction_type"] == "patreon_link"


def test_redact_discord_token():
    fake_token = "M" + ("a" * 23) + "." + ("b" * 6) + "." + ("c" * 27)
    redacted, events = redactor.redact_summary({"session_tldr": f"token: {fake_token}"}, "s7")
    assert "[DISCORD_TOKEN_REDACTED]" in redacted["session_tldr"]
    assert events[0]["redaction_type"] == "discord_token"


def test_no_redactions_when_clean():
    redacted, events = redactor.redact_summary({"session_tldr": "Refactored the search module."}, "s8")
    assert events == []
    assert "needs_review" not in redacted


def test_flags_needs_review_over_threshold():
    text = (
        "emails: a@example.com b@example.com c@example.com d@example.com"
    )
    redacted, events = redactor.redact_summary({"session_tldr": text}, "s9")
    assert len(events) == 4
    assert redacted["needs_review"] is True
    assert "review_reason" in redacted


def test_does_not_flag_at_or_below_threshold():
    text = "emails: a@example.com b@example.com c@example.com"
    redacted, events = redactor.redact_summary({"session_tldr": text}, "s10")
    assert len(events) == 3
    assert "needs_review" not in redacted


def test_recurses_into_nested_lists_and_dicts():
    summary = {
        "learnings": ["contact fake.user@example.com for help"],
        "nested": {"tags": ["ghp_" + "z" * 36]},
    }
    redacted, events = redactor.redact_summary(summary, "s11")
    assert "[EMAIL_REDACTED]" in redacted["learnings"][0]
    assert "[GH_TOKEN_REDACTED]" in redacted["nested"]["tags"][0]
    assert len(events) == 2


def test_original_value_is_masked_not_stored_raw():
    text = f"ghp_{'x' * 36}"
    _, events = redactor.redact_summary({"session_tldr": text}, "s12")
    assert events[0]["original_value"] != text
    assert text not in events[0]["original_value"]


def test_writes_to_sqlite_redaction_log(tmp_path):
    db_path = tmp_path / "test.db"
    text = f"ghp_{'q' * 36}"
    redactor.redact_summary({"session_tldr": text}, "s13", db_path=str(db_path))

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT session_id, redaction_type, manually_reviewed FROM redaction_log").fetchall()
    conn.close()

    assert len(rows) == 1
    assert rows[0][0] == "s13"
    assert rows[0][1] == "github_token"
    assert rows[0][2] == 0


def test_writes_log_file(tmp_path):
    text = f"ghp_{'w' * 36}"
    redactor.redact_summary({"session_tldr": text}, "s14")
    for handler in redactor.logger.handlers:
        handler.flush()
    assert redactor.LOG_PATH.exists()
    content = redactor.LOG_PATH.read_text(encoding="utf-8")
    assert "github_token" in content
    assert text not in content
