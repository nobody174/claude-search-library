"""Command-line interface for Claude Search Library."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv

# See server.py's matching load_dotenv() call for why this is needed even
# though python-dotenv has been a listed dependency since day one: without
# it, this only ever worked because a human/agent manually exported .env
# into the shell first.
load_dotenv(Path(__file__).resolve().parent / ".env")

# Windows consoles default to a legacy codepage (e.g. cp1252) that can't
# encode characters like the em-dashes and arrows Claude's summaries often
# contain, crashing click.echo with UnicodeEncodeError. Force UTF-8 output.
if sys.platform == "win32":
    for _stream_name in ("stdout", "stderr"):
        _stream = getattr(sys, _stream_name)
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")


def _print_results_table(results: list) -> None:
    if not results:
        click.echo("No results found.")
        return

    for r in results:
        click.echo(f"\n[{r['relevance_score']:.2f}] {r.get('title') or '(untitled)'}")
        click.echo(f"  session_id: {r['session_id']}")
        if r.get("tldr"):
            click.echo(f"  tldr:       {r['tldr']}")
        click.echo(f"  source:     {r.get('source')} ({r.get('device')})")
        click.echo(f"  created_at: {r.get('created_at')}")
        if r.get("top_pattern"):
            click.echo(f"  pattern:    {r['top_pattern']}")
        if r.get("search_type"):
            click.echo(f"  found via:  {r['search_type']}")


class DefaultSearchGroup(click.Group):
    """A Group that treats an unrecognized first argument as a search query
    instead of failing with "no such command" — so `claude-search "query"`
    works alongside `claude-search collect`, `claude-search sync`, etc.
    """

    def resolve_command(self, ctx: click.Context, args: list):
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError:
            return "query", query_command, args


@click.group(cls=DefaultSearchGroup, no_args_is_help=True)
def cli() -> None:
    """claude-search: search your Claude chat history.

    Run with a bare query for a quick semantic search, or use a subcommand
    for collection, processing, advanced search, or sync.
    """


@cli.command(name="query", hidden=True)
@click.argument("query")
def query_command(query: str) -> None:
    """Internal: bare-query fallback used by DefaultSearchGroup."""
    from src.search import search as run_search

    results = run_search(query, mode="semantic", top_k=10)
    _print_results_table(results)


@cli.command()
@click.option("--watch", is_flag=True, help="Run collection continuously")
@click.option("--dry-run", is_flag=True, help="Show what would be collected without writing")
@click.option(
    "--source", "sources",
    multiple=True,
    type=click.Choice(["claude-ai", "vscode", "claude-code", "claude-desktop", "cowork", "local"]),
    help="Collect from only this source (repeatable). Default: all sources.",
)
@click.option(
    "--fail-fast", is_flag=True,
    help="Stop on the first collector/storage error instead of logging and continuing "
         "(default: off, suited to automated/cron runs).",
)
def collect(watch: bool, dry_run: bool, sources: tuple, fail_fast: bool) -> None:
    """Collect new chats from all configured sources."""
    from src.collector import watch as watch_collect
    from src.orchestration import run_collection

    source_list = list(sources) or None

    if dry_run:
        click.echo("Dry run: scanning sources without importing...")
        result = run_collection(sources=source_list, fail_fast=fail_fast)
        click.echo(f"Would collect: {result['new']} new, {result['total']} total, {result['errors']} errors")
        return

    if watch:
        click.echo("Starting collection watch loop (Ctrl+C to stop)...")
        watch_collect()
    else:
        result = run_collection(sources=source_list, fail_fast=fail_fast)
        click.echo(json.dumps(result, indent=2))


@cli.command(name="import-export")
@click.argument("export_path", type=click.Path(exists=True))
@click.option(
    "--run-collect", is_flag=True,
    help="Run `collect --source claude-ai` immediately after converting.",
)
def import_export(export_path: str, run_collect: bool) -> None:
    """Import a claude.ai Data Export (Settings -> Export data ZIP or its
    conversations.json), converting it for the next `collect` to pick up."""
    from src.claude_export_import import import_official_export

    result = import_official_export(export_path)
    click.echo(json.dumps(result, indent=2))

    if run_collect:
        from src.orchestration import run_collection

        collect_result = run_collection(sources=["claude-ai"])
        click.echo(json.dumps(collect_result, indent=2))


@cli.command()
@click.option("--batch-size", default=10, show_default=True, help="Sessions per batch")
@click.option("--watch", is_flag=True, help="Run processing continuously")
def process(batch_size: int, watch: bool) -> None:
    """Summarize collected chats via the Claude API."""
    from src.processor import process_batch
    from src.storage import Storage

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise click.ClickException("ANTHROPIC_API_KEY is not set")

    def _run_once() -> dict:
        with Storage() as db:
            pending = [s["id"] for s in db.get_all_sessions() if s.get("status") == "new"]
        result = process_batch(pending, api_key=api_key, batch_size=batch_size)
        if result.get("succeeded"):
            with Storage() as db:
                db.export_summaries_to_jsonl()
        return result

    if watch:
        import time

        click.echo("Starting processing watch loop (Ctrl+C to stop)...")
        while True:
            result = _run_once()
            click.echo(json.dumps(result, indent=2))
            time.sleep(300)
    else:
        result = _run_once()
        click.echo(json.dumps(result, indent=2))


@cli.command(name="search")
@click.argument("query")
@click.option(
    "--mode",
    type=click.Choice(["semantic", "keyword", "hybrid"]),
    default="hybrid",
    show_default=True,
    help="semantic (by meaning, ChromaDB) | keyword (fast, FTS5) | hybrid (both, recommended)",
)
@click.option("--top-k", default=10, show_default=True)
@click.option("--filters", default=None, help='JSON filter object, e.g. \'{"source":"vscode"}\'')
def search_cmd(query: str, mode: str, top_k: int, filters: str) -> None:
    """Advanced search with mode selection and filters."""
    from src.search import search as run_search

    parsed_filters = json.loads(filters) if filters else None
    results = run_search(query, mode=mode, top_k=top_k, filters=parsed_filters)
    _print_results_table(results)


@cli.command()
@click.option("--verbose", is_flag=True, help="Print progress for each check")
@click.option("--json", "output_json", is_flag=True, help="Output the full report as JSON")
def verify(verbose: bool, output_json: bool) -> None:
    """Verify archive integrity and consistency (run before syncing)."""
    from src.storage import Storage

    if verbose:
        click.echo("Starting archive health check...\n")

    with Storage() as db:
        result = db.verify_archive(verbose=verbose)

    if output_json:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo("\n" + "=" * 60)
        click.echo("ARCHIVE INTEGRITY REPORT")
        click.echo("=" * 60)

        click.echo("Status: HEALTHY\n" if result["healthy"] else "Status: PROBLEMS DETECTED\n")
        click.echo(f"Checks passed: {result['checks_passed']}")
        click.echo(f"Checks failed: {result['checks_failed']}")

        click.echo("\nStatistics:")
        for key, value in result["stats"].items():
            click.echo(f"  {key}: {value}")

        if result["errors"]:
            click.echo("\nERRORS:")
            for error in result["errors"]:
                click.echo(f"  - {error}")

        if result["warnings"]:
            click.echo("\nWARNINGS:")
            for warning in result["warnings"]:
                click.echo(f"  - {warning}")

        click.echo("\n" + "=" * 60 + "\n")

    if not result["healthy"]:
        raise SystemExit(1)


@cli.command()
@click.option("--month", default=None, help="Report a single month, e.g. 2026-08")
@click.option("--quarter", default=None, help="Report a single quarter, e.g. 2026-Q3")
def costs(month: str, quarter: str) -> None:
    """Report API spend, optionally scoped to a month or quarter."""
    from src.cost_tracker import get_report

    if month and quarter:
        raise click.UsageError("Pass only one of --month or --quarter")

    report = get_report(month=month, quarter=quarter)
    click.echo(f"Period: {report['period']}")
    click.echo(f"Total calls: {report['calls']}")
    click.echo(f"Total cost:  ${report['total_cost_usd']:.4f}")
    if report["by_model"]:
        click.echo("\nBy model:")
        for model, stats in report["by_model"].items():
            click.echo(
                f"  {model}: {stats['calls']} calls, "
                f"{stats['input_tokens']} in / {stats['output_tokens']} out tokens, "
                f"${stats['cost_usd']:.4f}"
            )


@cli.command()
@click.argument("session_id")
@click.option(
    "--format", "export_format",
    type=click.Choice(["markdown"]),
    default="markdown",
    show_default=True,
    help="Export format",
)
@click.option("--output", default=None, help="Output file path (default: ~/.claude-search-library/exports/<id>.md)")
def export(session_id: str, export_format: str, output: str) -> None:
    """Export a session + its summary as a shareable file."""
    from src.export import export_session

    path = export_session(session_id, output_path=output)
    click.echo(f"Exported to {path}")


@cli.command()
@click.option("--older-than", default=365, show_default=True, help="Prune raw chat content older than this many days")
@click.option("--dry-run", is_flag=True, help="Report what would be pruned without deleting anything")
def prune(older_than: int, dry_run: bool) -> None:
    """Delete old raw chat content while keeping sessions/summaries searchable."""
    from src.maintenance import prune_sessions

    result = prune_sessions(older_than_days=older_than, dry_run=dry_run)
    click.echo(json.dumps(result, indent=2))


@cli.command()
@click.option("--pull", is_flag=True, help="Pull only")
@click.option("--push", is_flag=True, help="Push only")
@click.option("--watch", is_flag=True, help="Run continuously as a daemon")
@click.option(
    "--no-collect", is_flag=True,
    help="Skip collecting from local sources first (default: always collect, "
         "including the desktop-app collector, before syncing).",
)
def sync(pull: bool, push: bool, watch: bool, no_collect: bool) -> None:
    """Sync session data to/from GitHub. Defaults to bidirectional.

    Collects from every local source first (unless --no-collect) so
    anything new sitting only on this machine - most importantly the
    claude-desktop collector's freshly-cached conversations, which only
    exist locally until pushed - is included in the sync rather than
    requiring a separate `collect` step to remember to run first.
    """
    from src import crypto
    from src.orchestration import run_collection
    from src.sync import SyncWorker

    if not no_collect:
        click.echo("Collecting from local sources first...")
        collect_result = run_collection(fail_fast=False)
        click.echo(
            f"Collected {collect_result['new']} new session(s) "
            f"({collect_result['errors']} error(s))"
        )

    encryption_key = crypto.join_device_existing_setup()["encryption_key"]
    worker = SyncWorker(encryption_key=encryption_key)

    if watch:
        click.echo("Starting sync daemon (Ctrl+C to stop)...")
        worker.daemon_loop(collect_first=not no_collect)
        return

    if pull and not push:
        result = worker.pull_from_github()
    elif push and not pull:
        result = worker.push_to_github()
    else:
        result = worker.sync(direction="bidirectional")

    click.echo(json.dumps(result, indent=2))


if __name__ == "__main__":
    cli()
