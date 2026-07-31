# Task 3: Redaction & Privacy Module

Create the redaction module (`src/redactor.py`) for sensitive data masking.

## Requirements

1. **Function: `redact_summary(summary_dict: dict, session_id: str) -> tuple[dict, list]`**
   - Apply regex patterns to summaries
   - Match patterns in order of highest confidence
   - Replace matches with placeholders: `[API_KEY_REDACTED]`, etc.
   - Track redactions in audit trail
   - Return `(redacted_summary, redaction_events)`

2. **Redaction Patterns**
   - API keys: `api_?key.*[a-z0-9]{20,}` → `[API_KEY_REDACTED]`
   - GitHub tokens: `ghp_[a-z0-9]{36}` → `[GH_TOKEN_REDACTED]`
   - AWS keys: `AKIA[0-9A-Z]{16}` → `[AWS_KEY_REDACTED]`
   - Patreon URLs: `patreon\.com/[^\s]+` → `[PATREON_LINK]`
   - Email: email pattern → `[EMAIL_REDACTED]`
   - IP addresses → `[IP_REDACTED]`
   - Discord tokens → `[DISCORD_TOKEN_REDACTED]`

3. **Review Logic**
   - If > 3 redactions detected in one summary
   - Mark session as "needs_review"
   - Don't index until manually approved
   - Log reason in SQLite `redaction_log` table

4. **Logging**
   - Log all redactions to `~/.claude-search-library/logs/redaction.log`
   - Also store in SQLite `redaction_log` table
   - Include: timestamp, pattern type, confidence, replaced value

## Redaction Log Schema

```python
{
    "id": int,
    "session_id": str,
    "redaction_type": str,  # "api_key", "github_token", "email", etc.
    "original_value": str,  # MASKED (don't store real value)
    "redacted_value": str,
    "confidence_score": float,
    "redacted_at": str,
    "manually_reviewed": int  # 0 or 1
}
```

## Testing

- Test with examples containing secrets (use mock data, don't leak real secrets)
- Verify pattern matching accuracy
- Test flagging for review (>3 redactions)
- Verify logging

## Output File

Save as: `src/redactor.py`

---

**Paste into Claude Code!**
