import json
import zipfile

import pytest

from src.claude_export_import import import_official_export

CONVERSATIONS = [
    {
        "uuid": "conv-1",
        "name": "Debugging a race condition",
        "created_at": "2026-07-30T14:22:00Z",
        "updated_at": "2026-07-30T14:30:00Z",
        "chat_messages": [
            {"sender": "human", "text": "Why does this deadlock?", "created_at": "2026-07-30T14:22:05Z"},
            {
                "sender": "assistant",
                "created_at": "2026-07-30T14:22:15Z",
                "content": [{"type": "text", "text": "Check the lock ordering."}],
            },
        ],
    },
    {
        "uuid": "conv-2",
        "name": "Empty conversation",
        "chat_messages": [],
    },
]


def test_import_bare_json_conversations_list(tmp_path):
    export_file = tmp_path / "conversations.json"
    export_file.write_text(json.dumps(CONVERSATIONS), encoding="utf-8")

    output_dir = tmp_path / "out"
    result = import_official_export(str(export_file), output_dir=str(output_dir))

    assert result["converted"] == 1
    assert result["skipped"] == 1  # conv-2 has no messages

    written = json.loads((output_dir / "conv-1.json").read_text(encoding="utf-8"))
    assert written["title"] == "Debugging a race condition"
    assert written["messages"][0] == {
        "role": "user", "content": "Why does this deadlock?", "timestamp": "2026-07-30T14:22:05Z",
    }
    assert written["messages"][1] == {
        "role": "assistant", "content": "Check the lock ordering.", "timestamp": "2026-07-30T14:22:15Z",
    }


def test_import_zip_export(tmp_path):
    zip_path = tmp_path / "data-export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("conversations.json", json.dumps(CONVERSATIONS))
        zf.writestr("users.json", "{}")

    output_dir = tmp_path / "out"
    result = import_official_export(str(zip_path), output_dir=str(output_dir))

    assert result["converted"] == 1
    assert (output_dir / "conv-1.json").exists()


def test_import_single_conversation_object(tmp_path):
    export_file = tmp_path / "single.json"
    export_file.write_text(json.dumps(CONVERSATIONS[0]), encoding="utf-8")

    output_dir = tmp_path / "out"
    result = import_official_export(str(export_file), output_dir=str(output_dir))

    assert result["converted"] == 1


def test_import_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        import_official_export(str(tmp_path / "does-not-exist.zip"))


def test_import_zip_without_conversations_json_raises(tmp_path):
    zip_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("users.json", "{}")

    with pytest.raises(ValueError):
        import_official_export(str(zip_path))
