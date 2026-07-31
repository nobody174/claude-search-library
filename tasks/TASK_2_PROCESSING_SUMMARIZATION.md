# Task 2: Processing & Summarization Module

Create the processing module (`src/processor.py`) for Claude API summarization.

## Requirements

1. **Function: `summarize_chat(chat_dict: dict, api_key: str) -> dict`**
   - Concatenate all messages into narrative
   - Truncate to 16k tokens if needed
   - Call Claude API with system prompt (see below)
   - Parse JSON response (with error recovery)
   - Return summary dict with tldr, learnings, patterns, tags, etc.

2. **Function: `process_batch(session_ids: list, batch_size: int = 10)`**
   - Batch process sessions (respects rate limits)
   - Max 10 calls/minute to Claude API
   - Exponential backoff on transient failures
   - Log each success/failure with timestamp
   - Save summary as sidecar JSON

3. **Error Handling**
   - Parse JSON errors: retry up to 3 times
   - Timeout (>30s): skip session, log warning
   - Invalid schema: save to "needs_review" queue

4. **Logging**
   - Log to `~/.claude-search-library/logs/processing.log`
   - Include: timestamp, session_id, status, error (if any)

## System Prompt (for Claude API Call)

```
Analyze this chat session. Respond ONLY with valid JSON (no markdown, no preamble).

User and Claude worked on: [description]

Respond with exactly this structure:
{
    "session_tldr": "One sentence: what was accomplished",
    "learnings": [
        "Key takeaway 1",
        "Key takeaway 2"
    ],
    "patterns": [
        "Reusable workflow 1",
        "Reusable workflow 2"
    ],
    "tags": ["tag1", "tag2"],
    "mentioned_tools": ["Tool1", "Tool2"],
    "mentioned_languages": ["Python", "TypeScript"],
    "mentioned_frameworks": ["Phaser 3", "NeoForge"],
    "estimated_effort_minutes": 45,
    "topic_categories": ["minecraft-modding", "debugging"],
    "confidence_score": 0.92
}
```

## Output Format

Summary saved as JSON sidecar:
```
~/.claude-search-library/raw_chats/2026-07-31_desktop_12345.json          # Original
~/.claude-search-library/raw_chats/2026-07-31_desktop_12345_summary.json  # Generated
```

## Testing

- Test with sample chats
- Mock Claude API calls
- Verify JSON parsing error handling
- Test rate limiting (mock delays)

## Output File

Save as: `src/processor.py`

---

**Ready?** Paste this into Claude Code.
