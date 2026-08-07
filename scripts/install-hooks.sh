#!/bin/sh
# One-time setup: activates githooks/pre-push (see that file's own
# comments for what it does and why it isn't automatic). git hooks live
# in .git/hooks/, which git itself never version-controls - this copies
# the real, committed script there instead of relying on `git config
# core.hooksPath`, so it still works even if a user's git predates that
# option or has their own hooksPath already set for something else.
set -e

repo_root="$(git rev-parse --show-toplevel)"
cp "$repo_root/githooks/pre-push" "$repo_root/.git/hooks/pre-push"
chmod +x "$repo_root/.git/hooks/pre-push"

echo "Installed: every 'git push' will now run lint/security/tests first (see githooks/pre-push)."
echo "To skip once: git push --no-verify"
echo "To uninstall: rm .git/hooks/pre-push"
