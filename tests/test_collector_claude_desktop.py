"""Tests for src/collector.py:collect_from_claude_desktop() and its helpers.

Unlike test_collector_claude_code.py, this deliberately does NOT construct a
synthetic LevelDB/IndexedDB fixture to exercise the LevelDB-reading path
end-to-end. That store is a real Chromium IndexedDB database (LevelDB SST/log
files with Chromium's own key-encoding scheme) whose values are serialized
with V8's binary "structured clone" wire format, itself sometimes wrapped in
a Snappy-compressed envelope (see the long comment on _idb_ssv_decode() in
src/collector.py). Byte-for-byte reproducing that on disk isn't something a
hand-written fixture can reasonably do - the real verification for that path
was done manually against the actual local Claude desktop app store (copied,
never modified) and real Chrome-generated reference IndexedDB stores during
development; see CHANGELOG.md for that investigation's history.

What's tested here instead:
- The conversion/normalization logic (_convert_claude_desktop_tree,
  _extract_claude_desktop_content) against a fixture shaped exactly like
  what a decoded `chat_conversation_tree` react-query cache entry looks
  like in practice (confirmed against real decoded data).
- collect_from_claude_desktop()'s graceful-empty-list behavior when the
  IndexedDB store isn't present (e.g. any non-Windows machine, or Windows
  without the app installed) and when ccl_chromium_reader isn't installed.
"""
from src import collector


def _sample_tree():
    return {
        "uuid": "0515b9b7-b047-4779-a00d-ac50afa84aaa",
        "name": "Dark tech UI design for search library app",
        "created_at": "2026-08-03T10:14:35.529Z",
        "updated_at": "2026-08-03T10:14:42.310861Z",
        "chat_messages": [
            {
                "sender": "human",
                "created_at": "2026-08-03T10:14:37.421064Z",
                "content": [
                    {"type": "text", "text": "Help me design a dark tech UI."},
                ],
            },
            {
                "sender": "assistant",
                "created_at": "2026-08-03T10:14:42.310861Z",
                "content": [
                    {"type": "thinking", "thinking": "Let me think about colors..."},
                    {"type": "text", "text": "Here's a prompt for a dark tech UI."},
                ],
            },
        ],
    }


def test_extract_claude_desktop_content_drops_thinking_blocks():
    blocks = [
        {"type": "thinking", "thinking": "internal reasoning"},
        {"type": "text", "text": "visible answer"},
    ]
    assert collector._extract_claude_desktop_content(blocks) == "visible answer"


def test_extract_claude_desktop_content_handles_plain_string():
    assert collector._extract_claude_desktop_content("just a string") == "just a string"


def test_convert_claude_desktop_tree_shape():
    raw = collector._convert_claude_desktop_tree(_sample_tree())

    assert raw["id"] == "0515b9b7-b047-4779-a00d-ac50afa84aaa"
    assert raw["title"] == "Dark tech UI design for search library app"
    assert raw["created_at"] == "2026-08-03T10:14:35.529Z"
    assert raw["updated_at"] == "2026-08-03T10:14:42.310861Z"
    assert len(raw["messages"]) == 2
    assert raw["messages"][0] == {
        "role": "user",
        "content": "Help me design a dark tech UI.",
        "timestamp": "2026-08-03T10:14:37.421064Z",
    }
    # thinking block is dropped, only the text block survives
    assert raw["messages"][1]["role"] == "assistant"
    assert raw["messages"][1]["content"] == "Here's a prompt for a dark tech UI."


def test_convert_claude_desktop_tree_skips_conversations_with_no_text_messages():
    tree = _sample_tree()
    tree["chat_messages"] = [
        {"sender": "assistant", "created_at": "x", "content": [{"type": "thinking", "thinking": "only thinking"}]},
    ]
    assert collector._convert_claude_desktop_tree(tree) is None


def test_convert_claude_desktop_tree_requires_uuid_and_messages():
    assert collector._convert_claude_desktop_tree({"name": "no uuid", "chat_messages": []}) is None
    assert collector._convert_claude_desktop_tree({"uuid": "abc", "chat_messages": []}) is None


def test_convert_claude_desktop_tree_normalizes_via_normalize_session():
    raw = collector._convert_claude_desktop_tree(_sample_tree())
    session = collector.normalize_session(raw, "claude-desktop", "desktop", "/tmp/fake.json")

    assert session["id"] == "0515b9b7-b047-4779-a00d-ac50afa84aaa"
    assert session["source"] == "claude-desktop"
    assert session["message_count"] == 2
    assert session["user_message_count"] == 1
    assert session["assistant_message_count"] == 1


def test_collect_from_claude_desktop_missing_store_returns_empty(tmp_path):
    missing_root = tmp_path / "does-not-exist"
    assert collector.collect_from_claude_desktop(str(missing_root)) == []


def test_collect_from_claude_desktop_missing_leveldb_dir_returns_empty(tmp_path):
    # Root exists but the expected origin subdirectory doesn't.
    tmp_path.mkdir(exist_ok=True)
    assert collector.collect_from_claude_desktop(str(tmp_path)) == []
