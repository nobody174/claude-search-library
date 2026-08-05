# Claude Search Library — Code Flow

Traced from the real source (`src/orchestration.py`, `src/storage.py`,
`src/processor.py`, `src/redactor.py`, `src/embedder.py`, `src/sync.py`),
not the high-level summary in CLAUDE.md's "Architecture at a Glance."
Two separate flows, since they run independently and conflating them
would hide the actual decision points in each.

## 1. Collect → Process (`cli.py collect` / `cli.py process`)

```mermaid
flowchart TD
    Start([cli.py collect]) --> Orch[run_collection\nsrc/orchestration.py]
    Orch --> Sources{Which sources?}
    Sources -->|claude-ai| S1[collect_from_claude_ai]
    Sources -->|vscode| S2[collect_from_vscode]
    Sources -->|claude-code| S3[collect_from_claude_code]
    Sources -->|claude-desktop| S4[collect_from_claude_desktop\nLevelDB + Snappy + V8 decode]
    Sources -->|cowork| S5[collect_from_cowork]
    Sources -->|local| S6[collect_from_local_folder]

    S1 & S2 & S3 & S4 & S5 & S6 --> Normalize[normalize_session\nshared schema]
    Normalize --> Hash[store_session_with_hash\nsrc/storage.py]

    Hash --> Exists{Session id\nalready exists?}
    Exists -->|no, new content_hash| Insert[INSERT new session\nstatus = new]
    Exists -->|yes, same hash| Skip[skip: duplicate]
    Exists -->|yes, different hash| Update["UPDATE in place\nrefresh content_hash\nstatus reset to new"]

    Insert --> Queue[(sessions table\nstatus = new)]
    Update --> Queue
    Skip -.-> Done1([collect done])
    Queue --> Done1

    Done1 --> ProcStart([cli.py process])
    ProcStart --> Batch[process_batch\nsrc/processor.py]
    Batch --> Claude[summarize_chat\nClaude API call]
    Claude --> Redact[redact_summary\nsrc/redactor.py\n7 regex patterns, confidence-ordered]

    Redact --> ReviewCheck{"redaction count\n> REVIEW_THRESHOLD (3)?"}
    ReviewCheck -->|yes| Review["mark_for_review\nstatus = needs_review\nSKIPS indexing"]
    ReviewCheck -->|no| Store[store_summary +\nmark_as_processed]

    Store --> Index[_index_for_search]
    Index --> FTS[(search_index table\n+ FTS5 index)]
    Index --> Chroma[(ChromaDB\nembed_session)]

    Review --> NeedsReview([held for manual review\ncli.py review])
    FTS --> Done2([session searchable])
    Chroma --> Done2

    style Review fill:#5a3a1a,color:#fff
    style ReviewCheck fill:#3a3a1a,color:#fff
    style Exists fill:#3a3a1a,color:#fff
```

**Key decision points, not obvious from the module names alone:**
- `store_session_with_hash` doesn't just insert-or-skip — a same-`id`-different-hash
  case updates the existing row in place and resets `status` to `new` so it
  re-enters the processing queue (real bug fix, see CHANGELOG.md 2026-08-04).
- Redaction runs **before** anything is stored/indexed/embedded, not after
  — a session crossing the review threshold never reaches `search_index`
  or ChromaDB until a human clears it via `cli.py review`.

## 2. Sync (`cli.py sync`)

```mermaid
flowchart TD
    Start([cli.py sync]) --> Collect["Collect from all local sources\n(collect_first=True by default)"]
    Collect --> Direction{direction?}

    Direction -->|push or bidirectional| Push[push_to_github\nsrc/sync.py]
    Direction -->|pull or bidirectional| Pull[pull_from_github]

    Push --> Version[Read crsql_changes\nsince last_pushed_db_version]
    Version --> Encrypt1[Encrypt changeset\nFernet]
    Encrypt1 --> Commit1["git commit + push\nchangesets/&lt;device_id&gt;/&lt;db_version&gt;.enc"]

    Pull --> GitPull[git pull]
    GitPull --> Protocol{sync_protocol_version\nmatch?}
    Protocol -->|mismatch| Abort([abort: incompatible sync protocol])
    Protocol -->|match| OtherDevices["Find every other device's\nchangeset files"]

    OtherDevices --> Decrypt[Decrypt each changeset]
    Decrypt --> Apply["INSERT INTO crsql_changes\nreal per-column CRDT merge"]
    Apply --> SchemaCheck{"local schema_meta.version\n<= this code's SCHEMA_VERSION?"}
    SchemaCheck -->|no, DB is newer| SchemaErr([SchemaTooNewError\nfail loudly, don't guess])
    SchemaCheck -->|yes| Reindex[reindex_all\nrebuild ChromaDB + FTS5\nfor sessions touched by the merge]

    Commit1 --> Done([sync complete])
    Reindex --> Done

    style Protocol fill:#3a3a1a,color:#fff
    style SchemaCheck fill:#3a3a1a,color:#fff
    style Abort fill:#5a1a1a,color:#fff
    style SchemaErr fill:#5a1a1a,color:#fff
```

**Key decision points:**
- Push never sends whole rows — only the `crsql_changes` delta since this
  device's last push, one encrypted file per push.
- Pull's merge is real per-column CRDT (`INSERT INTO crsql_changes`), not
  a hand-written Last-Write-Wins comparison — two devices editing
  different fields of the same session both survive.
- Two independent compatibility guards, added for two different failure
  modes: `sync_protocol_version` catches an incompatible *wire format*
  between devices; `SchemaTooNewError` catches old code opening an
  already-migrated *local* database (see CHANGELOG.md's 2026-08-06 entry
  for why these are separate checks, not one).
