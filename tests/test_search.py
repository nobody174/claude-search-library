import pytest

from src import search
from src.storage import Storage


def _session(session_id, source="claude-ai", device="desktop", created_at="2026-07-31T14:00:00+00:00", raw_file_path=None):
    return {
        "id": session_id, "source": source, "device": device,
        "title": f"Title for {session_id}", "created_at": created_at, "updated_at": created_at,
        "duration_seconds": 0, "message_count": 2, "user_message_count": 1,
        "assistant_message_count": 1, "raw_file_path": raw_file_path, "summary_file_path": None,
        "content_hash": f"hash-{session_id}", "processed_at": None, "status": "processed",
        "review_reason": None, "synced_at": None, "sync_version": 1,
    }


def _summary(tldr="A tldr", patterns=None, tags=None):
    return {
        "session_tldr": tldr,
        "learnings": ["learning"],
        "patterns": patterns or ["a pattern"],
        "tags": tags or [],
        "mentioned_tools": [], "mentioned_languages": [], "mentioned_frameworks": [],
        "estimated_effort_minutes": 5, "topic_categories": [], "confidence_score": 0.7,
    }


@pytest.fixture(autouse=True)
def redirect_log(tmp_path, monkeypatch):
    monkeypatch.setattr(search, "LOG_PATH", tmp_path / "search.log")
    search.logger.handlers.clear()
    yield


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def test_keyword_search_matches_indexed_text(db_path):
    with Storage(db_path) as db:
        db.insert_session(_session("s1"))
        db.store_summary("s1", _summary(tldr="Fixed a minecraft crash"))
        db.index_session("s1", "Fixed a minecraft crash bug in rendering", "minecraft,crash")

    results = search.keyword_search("minecraft", db_path=db_path)
    assert len(results) == 1
    assert results[0]["session_id"] == "s1"
    assert results[0]["tldr"] == "Fixed a minecraft crash"


def test_keyword_search_no_match_returns_empty(db_path):
    with Storage(db_path) as db:
        db.insert_session(_session("s1"))
        db.index_session("s1", "something unrelated")

    results = search.keyword_search("minecraft", db_path=db_path)
    assert results == []


def test_keyword_search_ranks_title_match_higher(db_path):
    with Storage(db_path) as db:
        db.insert_session(_session("s1"))
        db.index_session("s1", "mentions python somewhere in the body")

        s2 = _session("s2")
        s2["title"] = "python refactor"
        db.insert_session(s2)
        db.index_session("s2", "python refactor session")

    results = search.keyword_search("python", db_path=db_path)
    assert results[0]["session_id"] == "s2"
    assert results[0]["relevance_score"] > results[1]["relevance_score"]


def test_keyword_search_respects_top_k(db_path):
    with Storage(db_path) as db:
        for i in range(5):
            sid = f"s{i}"
            db.insert_session(_session(sid))
            db.index_session(sid, "python session")

    results = search.keyword_search("python", top_k=2, db_path=db_path)
    assert len(results) == 2


def test_keyword_search_applies_source_filter(db_path):
    with Storage(db_path) as db:
        db.insert_session(_session("s1", source="claude-ai"))
        db.index_session("s1", "python code")
        db.insert_session(_session("s2", source="vscode"))
        db.index_session("s2", "python code")

    results = search.keyword_search("python", filters={"source": "vscode"}, db_path=db_path)
    assert len(results) == 1
    assert results[0]["session_id"] == "s2"


def test_keyword_search_applies_tags_filter(db_path):
    with Storage(db_path) as db:
        db.insert_session(_session("s1"))
        db.store_summary("s1", _summary(tags=["minecraft"]))
        db.index_session("s1", "python code")

        db.insert_session(_session("s2"))
        db.store_summary("s2", _summary(tags=["scraping"]))
        db.index_session("s2", "python code")

    results = search.keyword_search("python", filters={"tags": ["minecraft"]}, db_path=db_path)
    assert len(results) == 1
    assert results[0]["session_id"] == "s1"


def test_keyword_search_link_to_raw(db_path):
    with Storage(db_path) as db:
        db.insert_session(_session("s1", raw_file_path="/raw/s1.json"))
        db.index_session("s1", "python code")

    results = search.keyword_search("python", db_path=db_path)
    assert results[0]["link_to_raw"] == "file:///raw/s1.json"


def test_semantic_search_enriches_with_sqlite(db_path, monkeypatch):
    with Storage(db_path) as db:
        db.insert_session(_session("s1"))
        db.store_summary("s1", _summary(tldr="Semantic match tldr", patterns=["use X"]))

    monkeypatch.setattr(
        search, "_chroma_semantic_search",
        lambda query, top_k=10, chroma_path=None: [{"session_id": "s1", "relevance_score": 0.92, "metadata": {}}],
    )

    results = search.semantic_search("anything", db_path=db_path)
    assert len(results) == 1
    assert results[0]["tldr"] == "Semantic match tldr"
    assert results[0]["relevance_score"] == 0.92
    assert results[0]["top_pattern"] == "use X"


def test_semantic_search_skips_missing_sessions(db_path, monkeypatch):
    monkeypatch.setattr(
        search, "_chroma_semantic_search",
        lambda query, top_k=10, chroma_path=None: [{"session_id": "ghost", "relevance_score": 0.5, "metadata": {}}],
    )

    results = search.semantic_search("anything", db_path=db_path)
    assert results == []


def test_semantic_search_applies_filters(db_path, monkeypatch):
    with Storage(db_path) as db:
        db.insert_session(_session("s1", device="desktop"))
        db.store_summary("s1", _summary())
        db.insert_session(_session("s2", device="laptop"))
        db.store_summary("s2", _summary())

    monkeypatch.setattr(
        search, "_chroma_semantic_search",
        lambda query, top_k=10, chroma_path=None: [
            {"session_id": "s1", "relevance_score": 0.9, "metadata": {}},
            {"session_id": "s2", "relevance_score": 0.8, "metadata": {}},
        ],
    )

    results = search.semantic_search("anything", filters={"device": "laptop"}, db_path=db_path)
    assert len(results) == 1
    assert results[0]["session_id"] == "s2"


def test_search_routes_to_keyword_mode(db_path, monkeypatch):
    called = {}
    monkeypatch.setattr(search, "keyword_search", lambda q, **kw: called.setdefault("keyword", kw) or [])
    monkeypatch.setattr(search, "semantic_search", lambda q, **kw: called.setdefault("semantic", kw) or [])

    search.search("query", mode="keyword", db_path=db_path)
    assert "keyword" in called
    assert "semantic" not in called


def test_search_routes_to_semantic_mode_by_default(db_path, monkeypatch):
    called = {}
    monkeypatch.setattr(search, "keyword_search", lambda q, **kw: called.setdefault("keyword", kw) or [])
    monkeypatch.setattr(search, "semantic_search", lambda q, **kw: called.setdefault("semantic", kw) or [])

    search.search("query", db_path=db_path)
    assert "semantic" in called
    assert "keyword" not in called


def test_search_logs_query(db_path, monkeypatch, tmp_path):
    monkeypatch.setattr(search, "semantic_search", lambda q, **kw: [])
    search.search("logged query", db_path=db_path)

    for handler in search.logger.handlers:
        handler.flush()
    content = search.LOG_PATH.read_text(encoding="utf-8")
    assert "logged query" in content
