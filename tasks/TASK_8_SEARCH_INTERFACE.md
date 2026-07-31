# Task 8: Search Interface (CLI + REST API)

Create three modules for the search interface:
- `src/search.py`: Core search logic
- `cli.py`: Command-line interface
- `server.py`: Flask REST API

## Requirements for src/search.py

1. **Function: `semantic_search(query: str, top_k: int = 10, filters: dict = None) -> list[dict]`**
   - Call ChromaDB semantic_search
   - Apply filters if provided (source, tags, device, date_range)
   - Fetch full session + summary from SQLite
   - Return ranked results with relevance_score

2. **Function: `keyword_search(query: str, top_k: int = 10) -> list[dict]`**
   - SQL LIKE pattern match against search_index
   - Return results sorted by relevance

3. **Function: `search(query: str, mode: str = "semantic", **kwargs) -> list[dict]`**
   - Route to semantic or keyword search
   - Apply filters (source, device, date_range, tags)
   - Log search to `search.log`

## Requirements for cli.py (Click CLI)

1. **Command: `claude-search <query>`**
   - Basic semantic search
   - Print results in table format
   - Example: `claude-search "minecraft mod debugging"`

2. **Command: `claude-search collect [--watch] [--dry-run]`**
   - Trigger data collection
   - `--watch`: run continuously
   - `--dry-run`: show what would be collected

3. **Command: `claude-search process [--batch-size N] [--watch]`**
   - Trigger summarization
   - `--batch-size`: default 10
   - `--watch`: run continuously

4. **Command: `claude-search search <query> [--mode semantic|keyword] [--top-k N] [--filters JSON]`**
   - Advanced search with filters
   - Example: `claude-search search "async" --filters '{"source":"vscode"}'`

5. **Command: `claude-search sync [--pull] [--push] [--watch]`**
   - Trigger sync operations
   - Default: bidirectional

Use Click library for CLI structure.

## Requirements for server.py (Flask REST API)

1. **GET /search?q=QUERY&top_k=10**
   - JSON response: `{results: [...], total_results: N, query_time_ms: X}`
   - Example: `GET http://localhost:7654/search?q=minecraft&top_k=5`

2. **GET /session/<session_id>**
   - Return full session + summary details
   - Include link to raw chat file

3. **GET /stats**
   - System stats: total sessions, by source, by status, etc.
   - Example response:
   ```json
   {
       "total_sessions": 42,
       "by_source": {"claude-ai": 15, "vscode": 20, "cowork": 7},
       "by_status": {"processed": 40, "needs_review": 2},
       "last_sync": "2026-07-31T14:22:00Z"
   }
   ```

4. **GET /devices**
   - List connected devices (sync status)
   - Show last sync time for each

5. **POST /review/<session_id>/approve**
   - Mark session as approved (for needs_review status)
   - Body: `{"approved": true, "notes": "..."}`

## Flask Setup

```python
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app, origins=["localhost", "127.0.0.1"])  # Allow phone access

@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('q', '')
    top_k = int(request.args.get('top_k', 10))
    # ... implementation
    return jsonify(results)
```

## CLI Examples

```bash
# Simple search
$ claude-search "async patterns"

# Advanced search
$ claude-search search "minecraft" --mode semantic --top-k 20

# Collect new chats
$ claude-search collect --watch

# Process summaries
$ claude-search process --batch-size 5

# Sync to GitHub
$ claude-search sync --push

# View stats
$ python3 server.py --port 7654 &
$ curl http://localhost:7654/stats | jq
```

## Result Format

```python
{
    "session_id": "...",
    "title": "Minecraft Mod Debugging",
    "tldr": "Solved async race condition in event handler",
    "source": "vscode",
    "device": "laptop",
    "created_at": "2026-07-31T14:22:00Z",
    "relevance_score": 0.87,
    "top_pattern": "Use Promise.all() for parallel event listeners",
    "link_to_raw": "file://~/.claude-search-library/raw_chats/2026-07-31_laptop_12345.json"
}
```

## Testing

- Test CLI commands
- Test Flask endpoints with curl
- Test search quality
- Test filter logic

## Output Files

Save as:
- `src/search.py`
- `cli.py`
- `server.py`

---

**Paste into Claude Code!**
