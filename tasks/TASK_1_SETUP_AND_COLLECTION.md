# Task 1: Setup & Data Collection Module

Create the data collection module (`src/collector.py`) for the Claude Search Library.

## Requirements

1. **Function: `collect_from_claude_ai(export_folder: str) -> list[dict]`**
   - Read JSON files from Claude.ai exports folder
   - Validate against normalized schema (see SPEC)
   - Return list of normalized chat dicts

2. **Function: `collect_from_vscode(extensions_path: str = None) -> list[dict]`**
   - Find Claude extension in `.vscode/extensions`
   - Extract chat history
   - Normalize to schema

3. **Function: `collect_from_cowork(cowork_path: str = None) -> list[dict]`**
   - Either fetch from local cache or API
   - Normalize to schema

4. **Function: `collect_from_local(folder_path: str) -> list[dict]`**
   - Watch folder for new JSON files
   - Auto-import and normalize

5. **Function: `collect_all() -> dict`**
   - Run all collectors
   - Handle errors gracefully
   - Return: `{"new": N, "errors": M, "total": T}`

6. **File watching with `watchdog` library**
   - `--watch` flag: runs collection on interval
   - Default interval: 300 seconds (5 minutes)

## Normalized Schema (Target Output)

```python
{
    "id": str,                      # Unique ID or content hash
    "source": str,                  # "claude-ai" | "vscode" | "cowork" | "local"
    "title": str,                   # Session title
    "created_at": str,              # ISO 8601
    "updated_at": str,              # Last message time
    "duration_seconds": int,         # estimate if available
    "message_count": int,
    "user_message_count": int,
    "assistant_message_count": int,
    "messages": [
        {
            "role": "user" | "assistant",
            "content": str,
            "timestamp": str,
            "tokens_approx": int
        }
    ],
    "device": str,                  # "desktop" | "laptop" | "phone"
    "tags": [],                     # Pre-filled or user-tagged
    "raw_path": str                 # File path to original
}
```

## Testing

- Include sample JSON exports in tests
- Test normalization logic
- Test file watching
- Mock file system operations

## Output File

Save as: `src/collector.py`

---

**Start building!** Paste this prompt into Claude Code (VS Code extension).
