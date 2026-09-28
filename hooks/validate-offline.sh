#!/usr/bin/env bash
# Manual verification: run the offline suite, the retrieval evals, and the MCP
# handshake.
#
# This is no longer wired to git automatically. It used to be the pre-commit
# hook, which made it the entry point of an unbounded recursion: the hook ran the
# suite, the suite committed in a worktree, that commit re-fired the hook, and
# the tree fanned out to 14+ concurrent copies of the suite, each rewriting the
# repository's .git/config on the way past. CI runs the same checks on six
# platforms across five Python versions, so nothing was lost but the warning
# that arrived after the push instead of before it.
#
# AGI_MEMORY_HOOK is the reentrancy bound, honoured here as well as in
# hooks.py: a hook reached from inside the suite must not start the suite again.
set -e

if [ -n "${AGI_MEMORY_HOOK:-}" ]; then
  echo "==> Already inside a hook chain (AGI_MEMORY_HOOK set) -- skipping."
  exit 0
fi
export AGI_MEMORY_HOOK=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$SCRIPT_DIR/src:$PYTHONPATH"

echo "==> Running offline test suite..."
python3 "$SCRIPT_DIR/tests/test_offline.py"

echo "==> Running L1 & L2 evaluations..."
python3 "$SCRIPT_DIR/tests/eval_l1.py"
python3 "$SCRIPT_DIR/tests/eval_l2.py"

echo "==> Verifying MCP handshake..."
python3 -m agi_memory.integrate test

echo "==> All offline validation checks passed!"
