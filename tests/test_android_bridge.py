"""Tests for src/android_bridge.py's pure parsing functions.

Only the parsing half is tested here (parse_conversation_list,
parse_message_bubbles, is_scroll_stalled, merge_scroll_pages,
messages_to_raw_export) - the device-driving half (connect_device,
launch_claude_app, dump_ui, tap_bounds, ...) shells out to a real `adb`
binary talking to real hardware, which no CI environment has. That half
was verified manually against a real Android device during development
(see CHANGELOG.md's 2026-08-06 entries) - same testing split
collect_from_claude_desktop() uses for its own untestable IndexedDB/
LevelDB path.

Fixtures in tests/fixtures/android/ are real `adb shell uiautomator
dump` output captured from an actual device during that manual
verification - not hand-constructed. real_conversation_dump.xml is a
genuinely mixed-role conversation (one user message, one assistant
reply spanning 3 paragraph nodes) which is exactly the case that caught
2 real bugs during development: a naive top-down container walk
collapsed every message into one giant group, and a naive x-position-
only check misclassified messages before the container-based approach
was used instead.
"""
from pathlib import Path

import pytest

from src.android_bridge import (
    is_scroll_stalled,
    merge_scroll_pages,
    messages_to_raw_export,
    parse_conversation_list,
    parse_message_bubbles,
    _screen_width_from_dump,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "android"


def _load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


# --- parse_message_bubbles ------------------------------------------------

def test_parse_message_bubbles_against_real_dump():
    xml = _load_fixture("real_conversation_dump.xml")
    width = _screen_width_from_dump(xml)

    bubbles = parse_message_bubbles(xml, width)

    assert len(bubbles) == 2
    assert bubbles[0]["role"] == "user"
    assert bubbles[0]["text"].startswith("Test message for CRL Android bridge verification")
    assert bubbles[1]["role"] == "assistant"
    assert bubbles[1]["text"].startswith("Got it")


def test_parse_message_bubbles_merges_multi_paragraph_assistant_reply():
    """Claude's real reply in the fixture is 3 separate TextView nodes
    inside one message-group container - the bug this specifically
    guards against is those 3 nodes staying split into 3 separate
    bubbles, or worse, merging with the unrelated user message above
    them."""
    xml = _load_fixture("real_conversation_dump.xml")
    width = _screen_width_from_dump(xml)

    bubbles = parse_message_bubbles(xml, width)
    assistant_text = bubbles[1]["text"]

    assert "Got it" in assistant_text
    assert "Quick clarification" in assistant_text
    assert "reviewing a UIAutomator dump script" in assistant_text
    # the user's message must not have leaked into the assistant's bubble
    assert "Test message for CRL" not in assistant_text


def test_parse_message_bubbles_excludes_chrome_text():
    xml = _load_fixture("real_conversation_dump.xml")
    width = _screen_width_from_dump(xml)

    bubbles = parse_message_bubbles(xml, width)
    all_text = " ".join(b["text"] for b in bubbles)

    assert "Claude is AI and can make mistakes" not in all_text
    assert "Please double-check responses" not in all_text


def test_parse_message_bubbles_empty_dump_returns_empty():
    xml = '<?xml version="1.0"?><hierarchy><node bounds="[0,0][1080,2123]" class="android.widget.FrameLayout" text="" /></hierarchy>'
    assert parse_message_bubbles(xml, screen_width=1080) == []


# --- parse_conversation_list ----------------------------------------------

def test_parse_conversation_list_against_real_sidebar_dump():
    xml = _load_fixture("real_sidebar_dump.xml")

    convos = parse_conversation_list(xml)

    titles = [c["title"] for c in convos]
    assert "CRL Android bridge verification testing" in titles
    assert "Plan for Pi-Menu public project !" in titles
    assert len(convos) == 10


def test_parse_conversation_list_excludes_sidebar_chrome():
    xml = _load_fixture("real_sidebar_dump.xml")

    convos = parse_conversation_list(xml)
    titles = {c["title"] for c in convos}

    for chrome_label in ("Chats", "Projects", "Artifacts", "Code", "Dispatch", "Starred", "Recents", "New chat"):
        assert chrome_label not in titles


def test_parse_conversation_list_bounds_are_the_raw_xml_string():
    xml = _load_fixture("real_sidebar_dump.xml")

    convos = parse_conversation_list(xml)
    target = next(c for c in convos if c["title"] == "CRL Android bridge verification testing")

    assert target["bounds"] == "[64,1942][881,1992]"


# --- is_scroll_stalled -----------------------------------------------------

def test_is_scroll_stalled_true_when_no_new_content():
    prev = [{"role": "assistant", "text": "hello"}]
    curr = [{"role": "assistant", "text": "hello"}]
    assert is_scroll_stalled(prev, curr) is True


def test_is_scroll_stalled_false_when_new_content_appears():
    prev = [{"role": "assistant", "text": "hello"}]
    curr = [{"role": "user", "text": "earlier message"}, {"role": "assistant", "text": "hello"}]
    assert is_scroll_stalled(prev, curr) is False


def test_is_scroll_stalled_true_when_curr_is_a_subset():
    """A scroll step that reveals LESS on screen (e.g. scrolled past
    the last message into empty space) must not be treated as new
    content."""
    prev = [{"role": "user", "text": "a"}, {"role": "assistant", "text": "b"}]
    curr = [{"role": "assistant", "text": "b"}]
    assert is_scroll_stalled(prev, curr) is True


# --- merge_scroll_pages -----------------------------------------------------

def test_merge_scroll_pages_dedupes_overlap_preserving_order():
    page1 = [{"role": "assistant", "text": "recent reply"}]
    page2 = [
        {"role": "user", "text": "earlier question"},
        {"role": "assistant", "text": "recent reply"},  # overlap with page1
    ]

    merged = merge_scroll_pages([page1, page2])

    assert merged == [
        {"role": "assistant", "text": "recent reply"},
        {"role": "user", "text": "earlier question"},
    ]


def test_merge_scroll_pages_empty_input():
    assert merge_scroll_pages([]) == []


# --- messages_to_raw_export -------------------------------------------------

def test_messages_to_raw_export_shape():
    bubbles = [
        {"role": "user", "text": "hi"},
        {"role": "assistant", "text": "hello there"},
    ]

    raw = messages_to_raw_export("Test Conversation", bubbles)

    assert raw["title"] == "Test Conversation"
    assert raw["id"] is None
    assert raw["messages"] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello there"},
    ]


def test_messages_to_raw_export_is_normalize_session_compatible():
    """Round-trip through the real normalize_session() to catch any
    schema drift between this module and collector.py's expectations."""
    from src.collector import normalize_session

    bubbles = [
        {"role": "user", "text": "hi"},
        {"role": "assistant", "text": "hello there"},
    ]
    raw = messages_to_raw_export("Test Conversation", bubbles)

    session = normalize_session(raw, "claude-android", "android-bridge")

    assert session["source"] == "claude-android"
    assert session["title"] == "Test Conversation"
    assert session["message_count"] == 2
    assert session["user_message_count"] == 1
    assert session["assistant_message_count"] == 1


# --- _screen_width_from_dump -------------------------------------------------

def test_screen_width_from_real_dump():
    xml = _load_fixture("real_conversation_dump.xml")
    assert _screen_width_from_dump(xml) == 1080


def test_screen_width_from_dump_raises_when_missing():
    from src.android_bridge import AndroidUIElementNotFoundError

    with pytest.raises(AndroidUIElementNotFoundError):
        _screen_width_from_dump("<hierarchy></hierarchy>")

# Built with assistance from Claude Code by Anthropic.
