import json

import pytest
from click.testing import CliRunner

import cli


@pytest.fixture
def runner():
    return CliRunner()


def test_bare_query_runs_semantic_search(runner, monkeypatch):
    calls = {}

    def fake_search(query, mode="semantic", top_k=10, **kwargs):
        calls["query"] = query
        calls["mode"] = mode
        return [
            {
                "session_id": "s1", "title": "Minecraft Mod Debugging", "tldr": "Fixed a crash",
                "source": "claude-ai", "device": "desktop", "created_at": "2026-07-31T14:00:00+00:00",
                "relevance_score": 0.9, "top_pattern": "Check stack traces",
            }
        ]

    monkeypatch.setattr("src.search.search", fake_search)

    result = runner.invoke(cli.cli, ["minecraft mod debugging"])

    assert result.exit_code == 0
    assert calls["query"] == "minecraft mod debugging"
    assert calls["mode"] == "semantic"
    assert "Minecraft Mod Debugging" in result.output
    assert "Fixed a crash" in result.output


def test_bare_no_query_shows_help(runner):
    result = runner.invoke(cli.cli, [])
    # Click's no_args_is_help convention exits 0 on --help but 2 for the
    # implicit no-args case; either way the help text should be printed.
    assert "Usage" in result.output


def test_search_subcommand_with_filters(runner, monkeypatch):
    calls = {}

    def fake_search(query, mode="semantic", top_k=10, filters=None, **kwargs):
        calls.update(query=query, mode=mode, top_k=top_k, filters=filters)
        return []

    monkeypatch.setattr("src.search.search", fake_search)

    result = runner.invoke(
        cli.cli,
        ["search", "async", "--mode", "keyword", "--top-k", "5", "--filters", '{"source":"vscode"}'],
    )

    assert result.exit_code == 0
    assert calls["query"] == "async"
    assert calls["mode"] == "keyword"
    assert calls["top_k"] == 5
    assert calls["filters"] == {"source": "vscode"}


def test_search_subcommand_no_results(runner, monkeypatch):
    monkeypatch.setattr("src.search.search", lambda *a, **kw: [])
    result = runner.invoke(cli.cli, ["search", "nothing-matches"])
    assert result.exit_code == 0
    assert "No results found." in result.output


def test_search_subcommand_defaults_to_hybrid_mode(runner, monkeypatch):
    calls = {}

    def fake_search(query, mode="semantic", top_k=10, filters=None, **kwargs):
        calls["mode"] = mode
        return []

    monkeypatch.setattr("src.search.search", fake_search)

    result = runner.invoke(cli.cli, ["search", "async patterns"])

    assert result.exit_code == 0
    assert calls["mode"] == "hybrid"


def test_search_subcommand_shows_search_type_when_present(runner, monkeypatch):
    monkeypatch.setattr(
        "src.search.search",
        lambda *a, **kw: [
            {
                "session_id": "s1", "title": "t", "tldr": "tldr",
                "source": "claude-ai", "device": "desktop", "created_at": "2026-07-31T14:00:00+00:00",
                "relevance_score": 0.8, "search_type": "keyword",
            }
        ],
    )

    result = runner.invoke(cli.cli, ["search", "async", "--mode", "hybrid"])

    assert result.exit_code == 0
    assert "found via:  keyword" in result.output


def test_collect_command_runs_collect_all(runner, monkeypatch):
    monkeypatch.setattr("src.collector.collect_all", lambda: {"new": 3, "errors": 0, "total": 3})
    result = runner.invoke(cli.cli, ["collect"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["new"] == 3


def test_collect_command_dry_run(runner, monkeypatch):
    monkeypatch.setattr("src.collector.collect_all", lambda: {"new": 5, "errors": 1, "total": 6})
    result = runner.invoke(cli.cli, ["collect", "--dry-run"])
    assert result.exit_code == 0
    assert "Would collect: 5 new, 6 total, 1 errors" in result.output


def test_collect_command_watch_invokes_watch_loop(runner, monkeypatch):
    called = {}
    monkeypatch.setattr("src.collector.watch", lambda: called.setdefault("watched", True))
    result = runner.invoke(cli.cli, ["collect", "--watch"])
    assert result.exit_code == 0
    assert called.get("watched") is True


def test_process_command_requires_api_key(runner, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = runner.invoke(cli.cli, ["process"])
    assert result.exit_code != 0
    assert "ANTHROPIC_API_KEY" in result.output


def test_process_command_runs_batch(runner, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")

    class FakeStorage:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_all_sessions(self):
            return [{"id": "s1", "status": "new"}, {"id": "s2", "status": "processed"}]

    monkeypatch.setattr("src.storage.Storage", lambda *a, **kw: FakeStorage())

    captured = {}
    def fake_process_batch(session_ids, api_key, batch_size):
        captured["session_ids"] = session_ids
        captured["batch_size"] = batch_size
        return {"succeeded": session_ids, "failed": [], "needs_review": []}

    monkeypatch.setattr("src.processor.process_batch", fake_process_batch)

    result = runner.invoke(cli.cli, ["process", "--batch-size", "3"])

    assert result.exit_code == 0
    assert captured["session_ids"] == ["s1"]
    assert captured["batch_size"] == 3


def test_sync_command_default_bidirectional(runner, monkeypatch):
    monkeypatch.setattr("src.crypto.join_device_existing_setup", lambda: {"encryption_key": b"key"})

    class FakeWorker:
        def __init__(self, encryption_key):
            pass

        def sync(self, direction="bidirectional"):
            return {"direction": direction, "files_changed": 0}

    monkeypatch.setattr("src.sync.SyncWorker", FakeWorker)

    result = runner.invoke(cli.cli, ["sync"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["direction"] == "bidirectional"


def test_sync_command_pull_only(runner, monkeypatch):
    monkeypatch.setattr("src.crypto.join_device_existing_setup", lambda: {"encryption_key": b"key"})

    class FakeWorker:
        def __init__(self, encryption_key):
            pass

        def pull_from_github(self):
            return {"direction": "pull", "files_changed": 2}

    monkeypatch.setattr("src.sync.SyncWorker", FakeWorker)

    result = runner.invoke(cli.cli, ["sync", "--pull"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["direction"] == "pull"
