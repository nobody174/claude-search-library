import json
from types import SimpleNamespace

import anthropic
import pytest

from src import processor


VALID_SUMMARY = {
    "session_tldr": "Fixed a Minecraft mod crash.",
    "learnings": ["Check stack traces first"],
    "patterns": ["Reproduce, then bisect"],
    "tags": ["minecraft", "debugging"],
    "mentioned_tools": ["NeoForge"],
    "mentioned_languages": ["Java"],
    "mentioned_frameworks": ["NeoForge"],
    "estimated_effort_minutes": 30,
    "topic_categories": ["minecraft-modding"],
    "confidence_score": 0.9,
}

SAMPLE_CHAT = {
    "id": "chat-1",
    "title": "Minecraft Mod Debugging",
    "messages": [
        {"role": "user", "content": "Why does my mod crash on load?"},
        {"role": "assistant", "content": "Let's check the stack trace."},
    ],
}


def _fake_response(text: str):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


@pytest.fixture(autouse=True)
def redirect_log(tmp_path, monkeypatch):
    monkeypatch.setattr(processor, "LOG_PATH", tmp_path / "processing.log")
    monkeypatch.setattr(processor, "NEEDS_REVIEW_DIR", tmp_path / "needs_review")
    processor.logger.handlers.clear()
    yield


def test_summarize_chat_success(monkeypatch):
    monkeypatch.setattr(
        anthropic.Anthropic,
        "with_options",
        lambda self, **kw: SimpleNamespace(
            messages=SimpleNamespace(
                create=lambda **kwargs: _fake_response(json.dumps(VALID_SUMMARY))
            )
        ),
    )

    result = processor.summarize_chat(SAMPLE_CHAT, api_key="fake-key")
    assert result == VALID_SUMMARY


def test_summarize_chat_retries_on_bad_json_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_create(**kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            return _fake_response("not json")
        return _fake_response(json.dumps(VALID_SUMMARY))

    monkeypatch.setattr(
        anthropic.Anthropic,
        "with_options",
        lambda self, **kw: SimpleNamespace(messages=SimpleNamespace(create=fake_create)),
    )

    result = processor.summarize_chat(SAMPLE_CHAT, api_key="fake-key")
    assert result == VALID_SUMMARY
    assert calls["n"] == 2


def test_summarize_chat_exhausts_retries_raises(monkeypatch):
    monkeypatch.setattr(
        anthropic.Anthropic,
        "with_options",
        lambda self, **kw: SimpleNamespace(
            messages=SimpleNamespace(create=lambda **kwargs: _fake_response("still not json"))
        ),
    )

    with pytest.raises(ValueError):
        processor.summarize_chat(SAMPLE_CHAT, api_key="fake-key")


def test_summarize_chat_invalid_schema_saves_needs_review(monkeypatch, tmp_path):
    incomplete = {"session_tldr": "missing everything else"}
    monkeypatch.setattr(
        anthropic.Anthropic,
        "with_options",
        lambda self, **kw: SimpleNamespace(
            messages=SimpleNamespace(create=lambda **kwargs: _fake_response(json.dumps(incomplete)))
        ),
    )

    with pytest.raises(ValueError):
        processor.summarize_chat(SAMPLE_CHAT, api_key="fake-key")

    review_file = processor.NEEDS_REVIEW_DIR / "chat-1.json"
    assert review_file.exists()


def test_parse_summary_json_strips_markdown_fences():
    fenced = "```json\n" + json.dumps(VALID_SUMMARY) + "\n```"
    assert processor._parse_summary_json(fenced) == VALID_SUMMARY


def test_truncate_to_token_limit_short_text_unchanged():
    text = "short text"
    assert processor._truncate_to_token_limit(text, max_tokens=1000) == text


def test_truncate_to_token_limit_long_text_truncated():
    text = "x" * 10000
    result = processor._truncate_to_token_limit(text, max_tokens=100)
    assert len(result) <= 100 * 4 + len("\n\n[...truncated...]")
    assert result.endswith("[...truncated...]")


def test_process_batch_rate_limiting(monkeypatch, tmp_path):
    sessions_dir = tmp_path / "raw_chats"
    sessions_dir.mkdir()

    session_ids = []
    for i in range(3):
        sid = f"chat-{i}"
        session_ids.append(sid)
        chat = dict(SAMPLE_CHAT)
        chat["id"] = sid
        (sessions_dir / f"{sid}.json").write_text(json.dumps(chat), encoding="utf-8")

    monkeypatch.setattr(processor, "summarize_chat", lambda chat_dict, api_key: VALID_SUMMARY)
    sleep_calls = []
    monkeypatch.setattr(processor.time, "sleep", lambda s: sleep_calls.append(s))
    monkeypatch.setattr(processor, "MAX_CALLS_PER_MINUTE", 2)

    results = processor.process_batch(session_ids, api_key="fake-key", sessions_dir=str(sessions_dir))

    assert set(results["succeeded"]) == set(session_ids)
    assert len(sleep_calls) == 1  # rate limit triggered once after 2 calls


def test_process_batch_missing_session_marked_failed(tmp_path):
    sessions_dir = tmp_path / "raw_chats"
    sessions_dir.mkdir()

    results = processor.process_batch(["does-not-exist"], api_key="fake-key", sessions_dir=str(sessions_dir))
    assert "does-not-exist" in results["failed"]


def test_process_batch_writes_summary_sidecar(monkeypatch, tmp_path):
    sessions_dir = tmp_path / "raw_chats"
    sessions_dir.mkdir()
    (sessions_dir / "chat-1.json").write_text(json.dumps(SAMPLE_CHAT), encoding="utf-8")

    monkeypatch.setattr(processor, "summarize_chat", lambda chat_dict, api_key: VALID_SUMMARY)

    results = processor.process_batch(["chat-1"], api_key="fake-key", sessions_dir=str(sessions_dir))

    assert results["succeeded"] == ["chat-1"]
    sidecar = sessions_dir / "chat-1_summary.json"
    assert sidecar.exists()
    assert json.loads(sidecar.read_text(encoding="utf-8")) == VALID_SUMMARY
