"""Vector embeddings module for Claude Search Library.

Wraps a local, persistent ChromaDB collection for semantic search over
session summaries. Embeddings are generated automatically by ChromaDB's
default embedding function and are local-only (not synced to GitHub).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import chromadb

logger = logging.getLogger(__name__)

DEFAULT_CHROMA_PATH = Path.home() / ".claude-search-library" / "chromadb"
LOG_PATH = Path.home() / ".claude-search-library" / "logs" / "embeddings.log"
COLLECTION_NAME = "session_embeddings"

_client = None
_collection = None
_client_path = None


def _setup_file_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not any(isinstance(h, logging.FileHandler) and h.baseFilename == str(LOG_PATH) for h in logger.handlers):
        handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)


def get_collection(chroma_path: Optional[str] = None):
    """Return the ChromaDB collection, initializing the client if needed.

    Re-initializes if `chroma_path` differs from the currently open client's
    path (mainly useful for tests using a temporary directory).
    """
    global _client, _collection, _client_path
    _setup_file_logging()

    path = str(chroma_path) if chroma_path else str(DEFAULT_CHROMA_PATH)
    if _collection is not None and _client_path == path:
        return _collection

    Path(path).mkdir(parents=True, exist_ok=True)
    _client = chromadb.PersistentClient(path=path)
    _collection = _client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    _client_path = path
    return _collection


def _build_document(summary_dict: dict) -> str:
    tldr = summary_dict.get("session_tldr") or summary_dict.get("tldr") or ""
    learnings = summary_dict.get("learnings") or []
    patterns = summary_dict.get("patterns") or []
    learnings_text = "\n".join(learnings) if isinstance(learnings, list) else str(learnings)
    patterns_text = "\n".join(patterns) if isinstance(patterns, list) else str(patterns)
    return f"{tldr}\n\n{learnings_text}\n\n{patterns_text}".strip()


def _build_metadata(summary_dict: dict) -> dict:
    tags = summary_dict.get("tags") or []
    tags_string = ",".join(tags) if isinstance(tags, list) else str(tags)
    return {
        "source": summary_dict.get("source") or "",
        "device": summary_dict.get("device") or "",
        "created_at": summary_dict.get("created_at") or "",
        "tags": tags_string,
        "confidence": float(summary_dict.get("confidence_score") or 0.0),
    }


def embed_session(session_id: str, summary_dict: dict, chroma_path: Optional[str] = None) -> bool:
    """Embed a session's summary into ChromaDB.

    Concatenates tldr + learnings + patterns as the document text and
    attaches source/device/created_at/tags/confidence as metadata.
    Returns True on success, False if embedding failed (logged either way).
    """
    _setup_file_logging()
    try:
        collection = get_collection(chroma_path)
        document = _build_document(summary_dict)
        metadata = _build_metadata(summary_dict)

        collection.upsert(
            ids=[session_id],
            documents=[document],
            metadatas=[metadata],
        )
        logger.info("session_id=%s status=embedded", session_id)
        return True
    except Exception as e:
        logger.error("session_id=%s status=embed_failed error=%s", session_id, e)
        return False


def semantic_search(query: str, top_k: int = 10, chroma_path: Optional[str] = None) -> list:
    """Run a semantic search against embedded session summaries.

    Returns a list of {session_id, relevance_score, metadata} dicts,
    ordered by relevance (closest first). relevance_score is derived from
    ChromaDB's cosine distance as (1 - distance), so higher is more similar.
    """
    _setup_file_logging()
    try:
        collection = get_collection(chroma_path)
        results = collection.query(query_texts=[query], n_results=top_k)
    except Exception as e:
        logger.error("query=%r status=search_failed error=%s", query, e)
        return []

    ids = results.get("ids", [[]])[0]
    distances = results.get("distances", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]

    output = []
    for session_id, distance, metadata in zip(ids, distances, metadatas):
        output.append(
            {
                "session_id": session_id,
                "relevance_score": 1 - distance,
                "metadata": metadata,
            }
        )
    return output


def delete_embedding(session_id: str, chroma_path: Optional[str] = None) -> bool:
    """Remove a session's embedding from ChromaDB (e.g. before re-processing)."""
    _setup_file_logging()
    try:
        collection = get_collection(chroma_path)
        collection.delete(ids=[session_id])
        logger.info("session_id=%s status=deleted", session_id)
        return True
    except Exception as e:
        logger.error("session_id=%s status=delete_failed error=%s", session_id, e)
        return False


def reindex_all(db_path: Optional[str] = None, chroma_path: Optional[str] = None) -> int:
    """Clear and rebuild the entire ChromaDB collection from SQLite.

    Iterates all processed sessions in storage, joins each with its stored
    summary, and re-embeds it. Returns the count of sessions re-embedded.
    """
    from src.storage import Storage

    _setup_file_logging()
    collection = get_collection(chroma_path)

    existing = collection.get()
    existing_ids = existing.get("ids", [])
    if existing_ids:
        collection.delete(ids=existing_ids)

    count = 0
    with Storage(db_path) as db:
        for session in db.get_all_sessions():
            if session.get("status") != "processed":
                continue
            summary = db.get_summary(session["id"])
            if summary is None:
                continue

            merged = dict(summary)
            merged["source"] = session.get("source")
            merged["device"] = session.get("device")
            merged["created_at"] = session.get("created_at")

            if embed_session(session["id"], merged, chroma_path=chroma_path):
                count += 1

    logger.info("reindex_all complete: %d sessions re-embedded", count)
    return count
