import pytest

from src import embedder
from src.storage import Storage


SUMMARY_A = {
    "session_tldr": "Fixed a crash in the Minecraft mod's rendering pipeline.",
    "learnings": ["OpenGL context must be bound before drawing"],
    "patterns": ["Reproduce, then bisect the pipeline"],
    "tags": ["minecraft", "graphics"],
    "confidence_score": 0.9,
    "source": "claude-ai",
    "device": "desktop",
    "created_at": "2026-07-31T14:22:00+00:00",
}

SUMMARY_B = {
    "session_tldr": "Wrote a Python script to scrape recipe websites.",
    "learnings": ["Use requests + BeautifulSoup for static pages"],
    "patterns": ["Rate-limit scraper requests"],
    "tags": ["python", "scraping"],
    "confidence_score": 0.8,
    "source": "vscode",
    "device": "laptop",
    "created_at": "2026-07-30T10:00:00+00:00",
}


@pytest.fixture(autouse=True)
def isolated_chroma(tmp_path, monkeypatch):
    monkeypatch.setattr(embedder, "_client", None)
    monkeypatch.setattr(embedder, "_collection", None)
    monkeypatch.setattr(embedder, "_client_path", None)
    monkeypatch.setattr(embedder, "LOG_PATH", tmp_path / "embeddings.log")
    embedder.logger.handlers.clear()
    yield str(tmp_path / "chromadb")


def test_embed_session_success(isolated_chroma):
    result = embedder.embed_session("sess-a", SUMMARY_A, chroma_path=isolated_chroma)
    assert result is True

    collection = embedder.get_collection(isolated_chroma)
    stored = collection.get(ids=["sess-a"])
    assert stored["ids"] == ["sess-a"]
    assert "rendering pipeline" in stored["documents"][0]
    assert stored["metadatas"][0]["source"] == "claude-ai"
    assert stored["metadatas"][0]["tags"] == "minecraft,graphics"


def test_embed_session_upserts(isolated_chroma):
    embedder.embed_session("sess-a", SUMMARY_A, chroma_path=isolated_chroma)
    updated = dict(SUMMARY_A, session_tldr="Updated tldr text")
    embedder.embed_session("sess-a", updated, chroma_path=isolated_chroma)

    collection = embedder.get_collection(isolated_chroma)
    stored = collection.get(ids=["sess-a"])
    assert len(stored["ids"]) == 1
    assert "Updated tldr text" in stored["documents"][0]


def test_semantic_search_returns_relevant_result(isolated_chroma):
    embedder.embed_session("sess-a", SUMMARY_A, chroma_path=isolated_chroma)
    embedder.embed_session("sess-b", SUMMARY_B, chroma_path=isolated_chroma)

    results = embedder.semantic_search("minecraft rendering bug", top_k=5, chroma_path=isolated_chroma)

    assert len(results) == 2
    assert results[0]["session_id"] == "sess-a"
    assert "relevance_score" in results[0]
    assert "metadata" in results[0]
    assert results[0]["metadata"]["source"] == "claude-ai"


def test_semantic_search_respects_top_k(isolated_chroma):
    embedder.embed_session("sess-a", SUMMARY_A, chroma_path=isolated_chroma)
    embedder.embed_session("sess-b", SUMMARY_B, chroma_path=isolated_chroma)

    results = embedder.semantic_search("python scraping", top_k=1, chroma_path=isolated_chroma)
    assert len(results) == 1


def test_semantic_search_empty_collection(isolated_chroma):
    results = embedder.semantic_search("anything", chroma_path=isolated_chroma)
    assert results == []


def test_delete_embedding(isolated_chroma):
    embedder.embed_session("sess-a", SUMMARY_A, chroma_path=isolated_chroma)
    result = embedder.delete_embedding("sess-a", chroma_path=isolated_chroma)
    assert result is True

    collection = embedder.get_collection(isolated_chroma)
    stored = collection.get(ids=["sess-a"])
    assert stored["ids"] == []


def test_delete_embedding_nonexistent_id_still_returns_true(isolated_chroma):
    # Chroma's delete is idempotent - deleting a missing id is not an error.
    result = embedder.delete_embedding("does-not-exist", chroma_path=isolated_chroma)
    assert result is True


def test_embed_session_handles_failure_gracefully(isolated_chroma, monkeypatch):
    def broken_upsert(*args, **kwargs):
        raise RuntimeError("simulated chroma failure")

    collection = embedder.get_collection(isolated_chroma)
    monkeypatch.setattr(collection, "upsert", broken_upsert)

    result = embedder.embed_session("sess-a", SUMMARY_A, chroma_path=isolated_chroma)
    assert result is False


def test_semantic_search_handles_failure_gracefully(isolated_chroma, monkeypatch):
    collection = embedder.get_collection(isolated_chroma)

    def broken_query(*args, **kwargs):
        raise RuntimeError("simulated chroma failure")

    monkeypatch.setattr(collection, "query", broken_query)

    results = embedder.semantic_search("test", chroma_path=isolated_chroma)
    assert results == []


def test_reindex_all(isolated_chroma, tmp_path):
    db_path = str(tmp_path / "test.db")
    with Storage(db_path) as db:
        session_a = {
            "id": "sess-a", "source": "claude-ai", "device": "desktop",
            "title": "t", "created_at": "2026-07-31T14:22:00+00:00", "updated_at": None,
            "duration_seconds": 0, "message_count": 2, "user_message_count": 1,
            "assistant_message_count": 1, "raw_file_path": None, "summary_file_path": None,
            "content_hash": "hash-a", "processed_at": None, "status": "processed",
            "review_reason": None, "synced_at": None, "sync_version": 1,
        }
        session_b = dict(session_a, id="sess-b", content_hash="hash-b", status="new")
        db.insert_session(session_a)
        db.insert_session(session_b)
        db.store_summary("sess-a", SUMMARY_A)
        db.store_summary("sess-b", SUMMARY_B)

    count = embedder.reindex_all(db_path=db_path, chroma_path=isolated_chroma)

    # Only sess-a is "processed"; sess-b ("new") should be skipped.
    assert count == 1
    collection = embedder.get_collection(isolated_chroma)
    stored = collection.get()
    assert stored["ids"] == ["sess-a"]


def test_reindex_all_clears_existing_embeddings_first(isolated_chroma, tmp_path):
    db_path = str(tmp_path / "test.db")
    embedder.embed_session("stale-session", SUMMARY_A, chroma_path=isolated_chroma)

    with Storage(db_path):
        pass  # empty DB, no processed sessions

    count = embedder.reindex_all(db_path=db_path, chroma_path=isolated_chroma)

    assert count == 0
    collection = embedder.get_collection(isolated_chroma)
    stored = collection.get()
    assert stored["ids"] == []
