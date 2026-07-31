# Task 9: Configuration & Initialization

Create configuration setup for the app.

## Requirements

1. **Create `config_template.yaml`** with sections:

```yaml
api:
  anthropic_api_key: ${ANTHROPIC_API_KEY}

storage:
  data_dir: ~/.claude-search-library
  db_path: ~/.claude-search-library/library.db
  chromadb_path: ~/.claude-search-library/chromadb
  raw_chats_dir: ~/.claude-search-library/raw_chats

sync:
  github_repo: github.com/nobody174/claude-search-library
  sync_interval: 300  # seconds
  github_token: ${GITHUB_TOKEN}

processing:
  batch_size: 10
  max_workers: 1
  rate_limit_per_min: 10
  timeout_per_chat: 30

redaction:
  flag_for_review_threshold: 3
  enable_logging: true

server:
  port: 7654
  host: localhost
  allowed_origins: ["localhost", "127.0.0.1"]

logging:
  level: INFO
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
```

2. **Function: `load_config(config_path: str = None) -> dict`**
   - Load YAML file
   - Validate required fields present
   - Merge with environment variable overrides
   - Support `${VAR_NAME}` substitution
   - Return config dict
   - Raise error if missing required fields

3. **Function: `create_directories(config: dict) -> bool`**
   - Ensure all required directories exist
   - Create if missing:
     - `data_dir`
     - `raw_chats_dir`
     - `chromadb_path`
     - `logs/`
   - Return True if successful

4. **Function: `validate_config(config: dict) -> list[str]`**
   - Check all required fields are present
   - Check file paths are writable
   - Check API key is set
   - Return list of validation errors (empty if valid)

5. **Main Initialization Entry Point**
   ```bash
   python3 -m src.storage --init
   ```
   - Creates DB schema
   - Initializes ChromaDB
   - Creates directories
   - Validates config
   - Print success message

## Config File Locations (Priority Order)

1. `./config.yaml` (current directory)
2. `~/.claude-search-library/config.yaml` (home directory)
3. Default template (built-in)

## Environment Variables

Supported overrides:
```
ANTHROPIC_API_KEY=sk-proj-...
DATA_DIR=~/.claude-search-library
DB_PATH=~/.claude-search-library/library.db
CHROMADB_PATH=~/.claude-search-library/chromadb
SYNC_INTERVAL=300
GITHUB_REPO=github.com/nobody174/claude-search-library
GITHUB_TOKEN=ghp_...
```

## Initialization Flow

```bash
$ python3 -m src.storage --init

1. Load config (from config.yaml or .env)
2. Validate config (all required fields)
3. Create directories
4. Initialize SQLite with cr-sqlite
5. Create all tables
6. Initialize ChromaDB
7. Create sync_metadata table
8. Print success message

Output:
✓ Config loaded from ./config.yaml
✓ Directories created
✓ SQLite initialized at ~/.claude-search-library/library.db
✓ ChromaDB initialized at ~/.claude-search-library/chromadb
✓ System ready for use
```

## Testing

- Test YAML parsing
- Test environment variable overrides
- Test directory creation
- Test config validation
- Test initialization on fresh machine

## Output Files

Create:
- `config_template.yaml` (in project root)
- `src/config.py` (config loading module)

---

**Paste into Claude Code!**
