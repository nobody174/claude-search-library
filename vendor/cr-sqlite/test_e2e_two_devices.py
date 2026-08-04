"""Full end-to-end test: two real devices, a real git remote (bare repo on
local disk standing in for GitHub), real encryption, real cr-sqlite. No
mocking anywhere in the sync path. Proves the whole rewritten stack works
together, not just its individual pieces.

Run from the project's venv: venv/Scripts/python.exe vendor/cr-sqlite/test_e2e_two_devices.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from git import Repo

from src import crypto
from src.storage import Storage
from src.sync import SyncWorker

WORKDIR = Path(tempfile.mkdtemp(prefix="csl_e2e_"))
print(f"Working in {WORKDIR}")

# --- Set up a real bare git repo as the "GitHub" remote ---
remote_path = WORKDIR / "remote.git"
Repo.init(str(remote_path), bare=True)

# --- Device A (desktop): clone, do real work, push ---
device_a_repo_path = WORKDIR / "device_a" / "repo"
device_a_repo_path.parent.mkdir(parents=True)
Repo.clone_from(str(remote_path), str(device_a_repo_path))
# A bare-remote clone has no commits yet; git needs at least one commit to push.
(device_a_repo_path / ".gitkeep").write_text("", encoding="utf-8")
repo_a = Repo(device_a_repo_path)
repo_a.index.add([".gitkeep"])
repo_a.index.commit("init")
repo_a.remote(name="origin").push()

encryption_key = crypto.derive_encryption_key("test-passphrase-e2e", "JBSWY3DPEHPK3PXP")

import src.sync as sync_module
sync_module._device_id = lambda: "desktop"  # monkeypatch for deterministic device ids

db_a_path = str(WORKDIR / "device_a" / "library.db")
worker_a = SyncWorker(encryption_key, repo_path=str(device_a_repo_path), db_path=db_a_path)

with Storage(db_a_path) as db:
    db.insert_session({
        "id": "s1", "source": "claude-code", "device": "desktop", "title": "Original title",
        "created_at": "2026-08-05T10:00:00Z", "updated_at": "2026-08-05T10:00:00Z",
        "status": "new",
    })
    db.store_summary("s1", {"tldr": "Initial summary", "learnings": [], "patterns": []})

result = worker_a.push_to_github()
print(f"A push #1: {result}")
assert result["files_changed"] >= 1, "expected a changeset to be pushed"

# --- Device B (laptop): clone the SAME remote, pull ---
sync_module._device_id = lambda: "laptop"
device_b_repo_path = WORKDIR / "device_b" / "repo"
device_b_repo_path.parent.mkdir(parents=True)
Repo.clone_from(str(remote_path), str(device_b_repo_path))

db_b_path = str(WORKDIR / "device_b" / "library.db")
worker_b = SyncWorker(encryption_key, repo_path=str(device_b_repo_path), db_path=db_b_path)

pull_result = worker_b.pull_from_github()
print(f"B pull #1: {pull_result}")

with Storage(db_b_path) as db:
    session = db.get_session("s1")
    summary = db.get_summary("s1")
assert session is not None, "B should have received the session via changeset"
assert session["title"] == "Original title"
assert summary["tldr"] == "Initial summary"
print("B correctly received A's session + summary via a real git remote.")

# --- THE REAL TEST: both devices edit DIFFERENT fields of the SAME session,
#     without syncing in between, then both sync. Both edits must survive. ---
with Storage(db_a_path) as db:
    db.update_session("s1", {"title": "Edited on desktop"})
sync_module._device_id = lambda: "desktop"
result = worker_a.push_to_github()
print(f"A push #2 (title edit): {result}")

with Storage(db_b_path) as db:
    db.update_session("s1", {"status": "processed"})
sync_module._device_id = lambda: "laptop"
# Real usage always pulls before pushing (that's what worker.sync("bidirectional")
# does, and what cli.py sync / the web UI's Sync button call) - this avoids a
# plain git non-fast-forward rejection when two devices push around the same
# time. That's a git-history-level concern, separate from (and unaffected by)
# the cr-sqlite CRDT merge this test is actually proving.
worker_b.pull_from_github()
result = worker_b.push_to_github()
print(f"B push #1 (status edit): {result}")

# Now A pulls B's changes too.
sync_module._device_id = lambda: "desktop"
worker_a.pull_from_github()

with Storage(db_a_path) as db:
    final_a = db.get_session("s1")
with Storage(db_b_path) as db:
    final_b = db.get_session("s1")

print(f"\nA final state: title={final_a['title']!r} status={final_a['status']!r}")
print(f"B final state: title={final_b['title']!r} status={final_b['status']!r}")

assert final_a["title"] == "Edited on desktop", "A's own title edit should survive"
assert final_a["status"] == "processed", "B's status edit should have merged in"
assert final_b["title"] == "Edited on desktop", "B should have pulled A's title edit"
assert final_b["status"] == "processed", "B's own status edit should survive"
assert final_a["title"] == final_b["title"] and final_a["status"] == final_b["status"], "devices must converge"

print("\nPASS: two real devices, real git remote, real encryption, real cr-sqlite —")
print("concurrent edits to different fields of the same session both survived and both devices converged.")

shutil.rmtree(WORKDIR, ignore_errors=True)
