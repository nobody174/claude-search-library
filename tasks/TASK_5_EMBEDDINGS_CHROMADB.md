# Task 5: Vector Embeddings & ChromaDB Module

Create the embeddings module (`src/embedder.py`) for ChromaDB integration.

## Requirements

1. **Initialize ChromaDB**
   - Create PersistentClient at `~/.claude-search-library/chromadb`
   - Get or create collection `"session_embeddings"`
   - Set up metadata schema
   - Use cosine similarity

2. **Function: `embed_session(session_id: str, summary_dict: dict) -> bool`**
   - Concatenate: `tldr + learnings + patterns`
   - Add to ChromaDB with metadata:
     - `source`, `device`, `created_at`, `tags`, `confidence_score`
   - Handle embeddings automatically (ChromaDB does it)
   - Return True if successful

3. **Function: `semantic_search(query: str, top_k: int = 10) -> list[dict]`**
   - Embed query
   - Query collection for top_k similar documents
   - Fetch metadata for each result
   - Return list of results with session_id, relevance_score, metadata

4. **Function: `delete_embedding(session_id: str) -> bool`**
   - Remove session from ChromaDB (for re-processing)

5. **Function: `reindex_all() -> int`**
   - Clear and rebuild entire ChromaDB collection
   - Iterate all processed sessions from SQLite
   - Re-embed all
   - Return count of re-embedded sessions

6. **Error Handling**
   - Handle embedding failures gracefully
   - Log to `logs/embeddings.log`

## ChromaDB Collection Setup

```python
import chromadb

client = chromadb.PersistentClient(
    path="~/.claude-search-library/chromadb"
)

collection = client.get_or_create_collection(
    name="session_embeddings",
    metadata={"hnsw:space": "cosine"}
)
```

## Adding to Collection

```python
collection.add(
    ids=[session_id],
    documents=[f"{tldr}\n\n{learnings_text}\n\n{patterns_text}"],
    metadatas=[{
        "source": source,
        "device": device,
        "created_at": created_at,
        "tags": tags_string,
        "confidence": confidence_score
    }]
)
```

## Testing

- Test with sample summaries
- Verify search quality
- Test re-indexing
- Test error handling

## Output File

Save as: `src/embedder.py`

---

**Hand to Claude Code!**
