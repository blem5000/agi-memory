"""Configuration and path resolution for agent-memory.

Single Source of Truth (SSoT) for paths, directories, and environment variable resolution.
Zero external dependencies (stdlib only).
"""
from __future__ import annotations

import os
import socket
from pathlib import Path

# How an agent's identity was established, and therefore how much it is worth.
#
# MCP and A2A both carry no actor field, and no client convention exists to hang
# one on across the 13 assistants we support. So identity here is *derived*, and
# the kind travels with it so nothing downstream can mistake a process for a
# person:
#
#   "declared" -- AGI_AGENT_ID was set by whoever launched the harness. Trusted
#                 as a label, not as proof: an agent can set its own env.
#   "process"  -- host:pid:harness, i.e. which OS process wrote this. Two
#                 sub-agents of one parent share all of it, so it separates
#                 concurrent *processes* and nothing finer. That is still the
#                 right granularity for stopping two agents from collapsing into
#                 one session, which is what it is used for.
#
# The distinction matters because the alternative -- stamping an id on a claim
# and calling it provenance -- makes the field a fabrication of exactly the
# thing it exists to make true.
DECLARED = "declared"
PROCESS = "process"
UNKNOWN = "unknown"


def resolve_agent_id(harness: str = "") -> tuple[str, str]:
    """(agent_id, kind) for this process. Never raises.

    agent_id is what the session-reuse key is built on, so it must be stable
    within a process and distinct between concurrent ones.
    """
    declared = (os.environ.get("AGI_AGENT_ID")
                or os.environ.get("AGENT_MEMORY_AGENT_ID") or "").strip()
    if declared:
        return declared[:120], DECLARED
    try:
        host = socket.gethostname() or "localhost"
    except Exception:
        host = "localhost"
    tag = harness.strip() or os.environ.get("AGI_HARNESS", "").strip() or "agent"
    return f"{host}:{os.getpid()}:{tag}"[:200], PROCESS


def agent_alive(agent_id: str) -> bool:
    """Is the process that wrote this session still running?

    This is the signal the old 12-hour window was guessing at. That window
    answered "is anyone still working on this project?" by asking "did
    anything happen recently?", which is why two concurrent agents shared a
    session and why a peer's work was reported as yours. Asking the OS whether
    the owning pid still exists answers the question directly.

    A declared id names an agent we cannot probe, so it counts as alive: only
    that agent may reuse its own session. Pid reuse can make a dead writer look
    alive, which costs one extra session row, never a merged one.
    """
    parts = (agent_id or "").split(":")
    if len(parts) < 2 or not parts[1].isdigit():
        return bool(agent_id)
    try:
        os.kill(int(parts[1]), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True   # running, just not ours to signal
    except (OSError, ValueError):
        return True
    return True


def attest_write_origin(origin: str | None) -> tuple[str, str]:
    """Downgrade a trust claim an MCP caller cannot back. Returns (origin, why).

    `origin` is the strongest field in the store: 'user-confirmed' outranks
    everything in recall ranking. Over MCP the argument is chosen by the model,
    so it is a claim with no witness -- thirteen assistants share one store, and
    any of them could otherwise mint the top trust tier on its own authority.
    That is memory poisoning at the write boundary, which is where it has to be
    stopped: contamination reduced later is contamination that already spread.

    AGI_TRUST_WRITE=1 re-enables the claim, for a human who wants a server they
    started themselves to record a confirmed fact on their behalf. That is the
    only way to overrule this, and it is deliberately a human's decision.
    """
    want = (origin or "").strip().lower()
    if want != "user-confirmed":
        return want, ""
    if os.environ.get("AGI_TRUST_WRITE", "").strip() in ("1", "true", "yes"):
        return want, ""
    return "agent-inferred", (
        "downgraded to agent-inferred: 'user-confirmed' is a claim about a human, "
        "and a model-chosen argument cannot attest one. Set AGI_TRUST_WRITE=1 on a "
        "server you started yourself if you mean it."
    )


def _resolve_base_dir() -> Path:
    env = os.environ.get("AGI_MEMORY_DIR") or os.environ.get("AGENT_MEMORY_DIR")
    if env:
        return Path(env)
    if (Path.home() / ".agi-memory").exists():
        return Path.home() / ".agi-memory"
    if (Path.home() / ".agent-memory").exists():
        return Path.home() / ".agent-memory"
    return Path.home() / ".agi-memory"


# Base directories
DATA_DIR = _resolve_base_dir()
VAULT_DIR = Path(os.environ.get("AGI_MEMORY_VAULT") or os.environ.get("AGENT_MEMORY_VAULT", DATA_DIR / "vault"))
DEFAULT_DB = Path(os.environ.get("AGI_MEMORY_DB") or os.environ.get("AGENT_MEMORY_DB", DATA_DIR / "memory.db"))
SESSION_DB = DEFAULT_DB
GRAPH_DB = Path(os.environ.get("AGI_MEMORY_GRAPH_DB") or os.environ.get("AGENT_MEMORY_GRAPH_DB", DEFAULT_DB))
LEGACY_CLAUDE_MEM_DB = Path(os.environ.get("CLAUDE_MEM_DB", Path.home() / ".claude-mem" / "claude-mem.db"))
SYNC_CONFIG_FILE = DATA_DIR / "sync.json"
DEFAULT_STATE_FILE = Path(os.environ.get("AGI_MEMORY_STATE") or os.environ.get("AGENT_MEMORY_STATE", DATA_DIR / "promoted.json"))


def get_data_dir() -> Path:
    """Return active data directory, respecting AGI_MEMORY_DIR or AGENT_MEMORY_DIR."""
    target = _resolve_base_dir()
    target.mkdir(parents=True, exist_ok=True)
    return target


def get_vault_dir(vault_dir: Path | str | None = None) -> Path:
    """Return active vault directory, respecting AGI_MEMORY_VAULT or AGENT_MEMORY_VAULT or argument."""
    if vault_dir:
        target = Path(vault_dir)
    else:
        env = os.environ.get("AGI_MEMORY_VAULT") or os.environ.get("AGENT_MEMORY_VAULT")
        target = Path(env) if env else get_data_dir() / "vault"
    target.mkdir(parents=True, exist_ok=True)
    return target


def get_default_db() -> Path:
    """Resolve active database path dynamically.

    Priority:
    1. AGI_MEMORY_DB / AGENT_MEMORY_DB env var
    2. CLAUDE_MEM_DB env var
    3. Legacy ~/.claude-mem/claude-mem.db if exists
    4. Base data dir memory.db
    """
    env_path = os.getenv("AGI_MEMORY_DB") or os.getenv("AGENT_MEMORY_DB") or os.getenv("CLAUDE_MEM_DB")
    if env_path:
        return Path(env_path)
    if LEGACY_CLAUDE_MEM_DB.exists():
        return LEGACY_CLAUDE_MEM_DB
    return get_data_dir() / "memory.db"


def get_graph_db() -> Path:
    """Resolve active graph database path dynamically."""
    env_path = os.getenv("AGI_MEMORY_GRAPH_DB") or os.getenv("AGENT_MEMORY_GRAPH_DB")
    if env_path:
        return Path(env_path)
    return get_default_db()


def get_state_path() -> Path:
    """Resolve state file path dynamically for promotion tracking."""
    env = os.environ.get("AGI_MEMORY_STATE") or os.environ.get("AGENT_MEMORY_STATE")
    if env:
        return Path(env)
    v_dir = get_vault_dir()
    vault_state = v_dir / "promoted.json"
    if vault_state.parent.exists():
        return vault_state
    return get_data_dir() / "promoted.json"
