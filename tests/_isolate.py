"""Point this test process at a throwaway memory store before agi_memory loads.

Imported first by every test entry point. Tests leaked into the developer's real
store repeatedly -- fixture memories under `p`, `p1`, `p-core`, `inflight-proj`,
`sample-agent-app`, pinned blocks, an episodic session -- and auto-sync pushed
them to the developer's git remote. Each leak was one block that isolated the
database but not the vault, or neither. Patching them one at a time kept
missing the next one, so isolation now happens once, per process, before any
path is resolved: agi_memory.config freezes its path constants at import.

Every override that outranks AGI_MEMORY_DIR is cleared. CLAUDE_MEM_DB is then
set inside the temp dir: get_default_db() treats that variable as an explicit
database path, and without it falls back to a legacy ~/.claude-mem database
whenever one exists on the developer's machine. Setting it pins the database to
the throwaway directory either way.

Deliberately NOT imported by tests/alias_coverage.py, which exists to measure
the developer's real vault.
"""
import atexit
import os
import shutil
import tempfile

_ROOT = tempfile.mkdtemp(prefix="agi-memory-test-")

for _var in ("AGI_MEMORY_DB", "AGENT_MEMORY_DB",
             "AGI_MEMORY_VAULT", "AGENT_MEMORY_VAULT",
             "AGI_MEMORY_GRAPH_DB", "AGENT_MEMORY_GRAPH_DB",
             "AGI_MEMORY_STATE", "AGENT_MEMORY_STATE",
             "AGENT_MEMORY_DIR"):
    os.environ.pop(_var, None)

os.environ["AGI_MEMORY_DIR"] = _ROOT
os.environ["CLAUDE_MEM_DB"] = os.path.join(_ROOT, "no-legacy-claude-mem.db")

atexit.register(shutil.rmtree, _ROOT, ignore_errors=True)
