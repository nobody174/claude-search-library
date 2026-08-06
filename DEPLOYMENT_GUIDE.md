# Deployment Guide

Step-by-step setup for Claude Search Library — first device, additional devices, and the web UI.

For command reference and quick commands once you're up and running, see the [README](README.md#common-commands). This guide covers the one-time setup flow in detail.

---

## Before You Start

You'll need:

- **Python 3.11+** and **Git** installed
- A **private** GitHub repository to hold your encrypted data (this is your personal archive — do not use a public repo for this)
- A GitHub **personal access token** with repo read/write access, for the sync module
- An **Anthropic API key** (for summarization)
- **Google Authenticator** (or any TOTP app) on your phone
- A password manager (LastPass, 1Password, Bitwarden, etc.) to store your master passphrase and backup codes — this project deliberately never stores the passphrase itself

---

## Step 1 — Clone and Install

```bash
git clone https://github.com/<your-username>/claude-search-library.git
cd claude-search-library

python3 -m venv venv

# Activate the virtual environment
source venv/bin/activate          # macOS / Linux
venv\Scripts\activate             # Windows (cmd.exe)
venv\Scripts\Activate.ps1         # Windows (PowerShell)

pip install -r requirements.txt
```

---

## Step 2 — Configure

Copy the config template and fill in your values:

```bash
cp config_template.yaml config.yaml
```

Edit `config.yaml` — most fields have sensible defaults, but check:

| Field | What to set it to |
|---|---|
| `sync.github_repo` | Your private GitHub repo, e.g. `github.com/yourname/my-claude-archive` |
| `api.anthropic_api_key` | Leave as `${ANTHROPIC_API_KEY}` and set the env var instead (see below) — don't hardcode it in the file |
| `sync.github_token` | Leave as `${GITHUB_TOKEN}` and set the env var instead |

Set the environment variables referenced by `${...}` in the config:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export GITHUB_TOKEN="ghp_..."
```

On Windows PowerShell:

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
$env:GITHUB_TOKEN = "ghp_..."
```

`config.yaml` is already covered by `.gitignore` — it will not be committed. Never commit real API keys or tokens.

---

## Step 3 — Initialize Storage

```bash
python3 -m src.storage --init
```

This creates:

- The SQLite database (with the full schema — sessions, summaries, search index, redaction log, sync metadata)
- The local ChromaDB collection for semantic search
- All required directories under `~/.claude-search-library/`

You should see a success line for each step (config loaded, directories created, SQLite initialized, ChromaDB initialized, system ready).

---

## Step 4 — Set Up Encryption (First Device Only)

This is the one-time setup for your **first** device. It generates a new TOTP secret and derives your encryption key.

```bash
python3 -m src.crypto --setup
```

You'll be walked through:

1. **A QR code is displayed** in your terminal — scan it into Google Authenticator (or any TOTP app).
2. **Enter your master passphrase** — pick something long and memorable (a passphrase of several random words is stronger than a short complex password). **Save this in your password manager now.** It is never stored by this tool, on this device or on GitHub — if you lose it, you lose access to your archive.
3. **Enter the 6-digit code** currently showing in your Authenticator app, to confirm the TOTP secret was captured correctly.
4. The tool derives your encryption key from both factors and stores the *encrypted* TOTP secret (`secrets.enc`) on GitHub — never the passphrase, never the raw key.

> **Note on backup codes:** `src/crypto.py` includes a `generate_backup_codes()` function for lost-phone recovery, but as of this release it isn't yet wired into the `--setup` CLI flow or displayed to you automatically. Until that's connected, your real recovery path if you lose your phone is re-adding the Authenticator entry from the same master passphrase (see [TROUBLESHOOTING.md](TROUBLESHOOTING.md#lost-my-phone-with-the-authenticator-app)) — treat the passphrase itself as the thing that must never be lost.

---

## Step 5 — Collect and Process Your Chats

```bash
# Gather chats from Claude.ai exports, VS Code extension, Cowork, and local folders
python3 cli.py collect

# See what would be collected without actually importing anything
python3 cli.py collect --dry-run
```

Then summarize them with the Claude API:

```bash
python3 cli.py process --batch-size 10
```

This calls the Claude API once per new session to extract a TL;DR, key learnings, and reusable patterns. It respects a rate limit automatically, so a large first-time batch may take a while — that's expected.

---

## Step 6 — Verify the Archive

Before syncing anything to GitHub, check that everything is internally consistent:

```bash
python3 cli.py verify
python3 cli.py verify --verbose   # see each of the 7 checks as it runs
```

A healthy archive exits with status code `0`. If something's off (a corrupted database, a mismatched hash, a broken JSONL mirror), `verify` exits non-zero and lists exactly what's wrong — see [TROUBLESHOOTING.md](TROUBLESHOOTING.md#archive-verification-failures) for how to fix each type of failure.

Get in the habit of running `verify` before every sync, especially early on.

---

## Step 7 — Start the Background Services

```bash
# Sync daemon — checks for local changes, pushes if any, pulls periodically (default: every 5 min)
python3 src/sync.py --daemon &

# Search API (used by the CLI's search command and the web UI)
python3 server.py --port 7654 &
```

Test that search works:

```bash
python3 cli.py search "your query here"
```

Or hit the API directly:

```bash
curl "http://localhost:7654/search?q=your+query&mode=hybrid" | jq
```

---

## Step 8 — Add a Second Device (Laptop, etc.)

On the new device:

```bash
git clone https://github.com/<your-username>/claude-search-library.git
cd claude-search-library

python3 -m venv venv
source venv/bin/activate     # or the Windows equivalent from Step 1

pip install -r requirements.txt
cp config_template.yaml config.yaml   # edit the same way as Step 2

export ANTHROPIC_API_KEY="sk-ant-..."
export GITHUB_TOKEN="ghp_..."

python3 -m src.storage --init
```

Then join the existing setup instead of creating a new one:

```bash
python3 -m src.crypto --join-device
```

You'll be prompted for:

1. **Your master passphrase** (the same one from Step 4 — pull it from your password manager)
2. This device fetches and decrypts the existing TOTP secret from GitHub, then shows you a QR code — scan it into Authenticator on this device (or the same phone) too
3. **Verify the current TOTP code** to confirm the join worked

Then pull everything down and start the daemons:

```bash
python3 src/sync.py --pull
python3 src/sync.py --daemon &
python3 server.py --port 7654 &
```

Your new device now shares the same encryption key and the same synced archive as your first device.

---

## Step 9 — Access from Your Phone (Web UI)

The web UI is served from the same Flask process as the REST API (`server.py`), from `public/index.html`.

1. Make sure `server.py` is running on a device your phone can reach on the same network (or via a VPN / tunnel for remote access — **do not** expose port 7654 directly to the public internet, see [Security](README.md#security)).
2. On your phone, open Safari (or any browser) and go to `http://<that-device's-local-ip>:7654`.
3. Enter your master passphrase and the current Authenticator code.
4. Start searching.

The web UI's setup step calls the server's `/setup` endpoint, which verifies your passphrase and TOTP against the same encrypted secret used everywhere else — it does not create a new device identity, so no separate `--join-device` step is needed for browser-only access.

---

## Step 10 — Capture Chats from Your Android Phone (Optional)

Unlike every other source, this one doesn't run automatically on
`cli.py sync` — it drives your phone's screen for real, over several
minutes per run, so it's opt-in and explicit. There are two genuinely
different reasons you'd set this up, covered separately below, since
the setup story (and what you're actually getting) differs.

### If you use the Claude Android app yourself

This captures your own Android-originated conversations directly.

1. On your Android phone: **Settings → Developer options** (if you don't
   see Developer options, go to **Settings → About phone** and tap
   **Build number** 7 times to enable it).
2. Inside Developer options, turn on **Wireless debugging**, then tap
   into it — note the IP address and port shown (e.g. `192.168.1.42:37281`).
3. Make sure your phone and the machine running Claude Search Library
   are on the same WiFi network.
4. On your computer:
   ```bash
   python3 cli.py android-connect 192.168.1.42:37281
   ```
   This connection is remembered — you only need to repeat this step
   when your phone's IP/port changes (usually after a WiFi reconnect;
   check the same Wireless debugging screen if a later collect fails).
5. Collect:
   ```bash
   python3 cli.py collect --source claude-android
   ```
   Your phone's screen will visibly change during this — it opens the
   Claude app, scrolls through your conversation list, opens each
   conversation, scrolls through it, and moves to the next. This is
   expected; don't use the phone for something else while it runs.

### If you have an iPhone and a spare/old Android device

**Claude.ai conversations are one cloud-synced account across every
mobile client** — a conversation you start on your iPhone's Claude app
shows up on any other device signed into the same account within
seconds, Android included. There's no separate export/API path for
iOS (confirmed directly by Anthropic — see BACKLOG.md), but an old
Android phone, a cheap secondhand device, or even an Android tablet
you already own can read those same iPhone conversations, since it's
just another client of the same account.

1. Set up the spare Android device once: install the Claude app, sign
   into the **same account** you use on your iPhone.
2. Follow the same 5 steps above (Developer options → Wireless
   debugging → `cli.py android-connect` → `cli.py collect --source
   claude-android`) on that spare device.
3. This will pick up **every conversation synced to the account** —
   both ones you've actually opened on the Android bridge device and
   (per the account-sync behavior above) ones you only ever typed on
   your iPhone. You don't need to open anything on the iPhone itself;
   the bridge device just needs to have synced.

This is a workaround, not an official Anthropic feature — it works
because of how account sync happens to behave, not because Anthropic
built cross-device export. If that ever changes, this path could stop
working; there's no SLA on it. See BACKLOG.md for the full research
trail (what was ruled out, what was verified, and why this doesn't
violate Anthropic's Consumer Terms — it never touches claude.ai's
servers directly, only reads your own phone's screen locally, same as
a screen reader would).

**Limitations, either way:**
- Slow — driving a real UI takes real time, expect several minutes for
  more than a handful of conversations.
- Requires the phone to be unlocked, on the same WiFi, and left alone
  while it runs.
- Message timestamps aren't available (the accessibility tree doesn't
  expose per-message times) — sessions get a timestamp from when
  they're collected, not when the conversation actually happened.

---

## Ongoing Use

Once set up, day-to-day usage is just:

```bash
python3 cli.py collect              # pull in new chats
python3 cli.py process              # summarize the new ones
python3 cli.py verify               # sanity check
python3 cli.py sync                 # bidirectional sync
```

Or leave `src/sync.py --daemon` running in the background and just use `cli.py collect` / `cli.py process` / `cli.py search` as needed — the daemon handles pushing and pulling automatically.

Consider scheduling `collect` and `process` on a cron job (or Task Scheduler on Windows) if you want new chats to show up without manual intervention.

## Next Steps

- Read [TROUBLESHOOTING.md](TROUBLESHOOTING.md) if anything above didn't go smoothly
- Read [CLAUDE.md](CLAUDE.md) for architecture decisions, module reference, and known limitations
- Read [CHANGELOG.md](CHANGELOG.md) for the full history of what's been built and fixed
