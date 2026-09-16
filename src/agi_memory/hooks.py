#!/usr/bin/env python3
"""Universal lifecycle hooks runner and installer for agent-memory.

Supported Lifecycle Events:
- session-start: Proactive memory context injection (pinned core blocks + top precedents)
- pre-compact:   Auto-promotion of L1 working memories into durable L2 graph before context compression
- session-end:   Instant background Git sync and compaction
- pre-commit:    Offline test suite and memory invariant validation
- post-commit:   Auto-records git commit message and diff insights into session memory

Supports:
- Claude Code (~/.claude/settings.json, .claude/settings.json)
- Antigravity CLI & IDE (~/.gemini/config/hooks.json, .agents/hooks.json)
- OpenCode (plugin: ~/.config/opencode/plugins/agent-memory.js, .opencode/plugins/agent-memory.js)
- OpenAI Codex (.codex/, git hooks)
- Cursor (.cursor/, git hooks)
- Windsurf (.windsurfrules, git hooks)
- Aider (.aider.conf.yml, git hooks)
- Git (.git/hooks/pre-commit, post-commit, pre-push)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from agi_memory.config import DATA_DIR, hidden_subprocess_kwargs
except ImportError:
    from config import DATA_DIR, hidden_subprocess_kwargs  # type: ignore[no-redef]

REPO_DIR = Path(__file__).resolve().parent
DEFAULT_HOOKS_DIR = DATA_DIR / "hooks"


def detect_python() -> str:
    venv_py = REPO_DIR / ".venv" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)
    if sys.prefix != sys.base_prefix:
        prefix_py = Path(sys.prefix) / "bin" / "python"
        if prefix_py.exists():
            return str(prefix_py)
    which_py = shutil.which("python3") or shutil.which("python")
    if which_py:
        return which_py
    return sys.executable


def detect_project(cwd: Path | None = None) -> str:
    """Detect current project name from environment, git root, or directory markers."""
    env_proj = os.getenv("AGENT_MEMORY_PROJECT") or os.getenv("PROJECT_NAME")
    if env_proj:
        return env_proj.strip()

    root = cwd or Path.cwd()
    # Check git root
    try:
        git_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(root),
            stderr=subprocess.DEVNULL,
            text=True,
            **hidden_subprocess_kwargs()
        ).strip()
        if git_root:
            return Path(git_root).name
    except Exception:
        pass

    # Check config files
    for parent in [root] + list(root.parents):
        for marker in ["pyproject.toml", "package.json", "Cargo.toml", "pubspec.yaml", "go.mod"]:
            f = parent / marker
            if f.exists():
                try:
                    txt = f.read_text(encoding="utf-8")
                    m = re.search(r'name\s*=\s*["\']([^"\']+)["\']', txt)
                    if m:
                        return m.group(1).strip()
                except Exception:
                    pass
                return parent.name
        if (parent / ".git").exists():
            return parent.name

    return root.name or "global"


def ensure_hooks_dir() -> Path:
    DEFAULT_HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_HOOKS_DIR


# ============================================================================
# Hook Implementations
# ============================================================================

# Startup context is injected into every session without anyone asking for it,
# and a single bootstrapped commit message can run to several thousand
# characters. Clip the preview; the id is right there and `memory_recall` or
# `agi-memory inspect <id>` returns the record in full when it is wanted.
_PREVIEW_CHARS = 400


def _clip(text: str, limit: int = _PREVIEW_CHARS) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + " ... (truncated -- inspect for full text)"


def hook_session_start(project: Optional[str] = None) -> None:
    """SessionStart / PreInvocation: Inject pinned blocks, precedents, and episodic recap into context."""
    proj = project or detect_project()
    sys.path.insert(0, str(REPO_DIR))

    pinned_blocks: List[Dict[str, Any]] = []
    recent_hits: List[str] = []
    episodic_recap: str = ""
    session_count: int = 0

    try:
        try:
            from agi_memory.layers.session_layer import SessionLayer
            from agi_memory.layers.episodic_layer import EpisodicLayer
        except ImportError:
            from layers.session_layer import SessionLayer
            from layers.episodic_layer import EpisodicLayer

        l1 = SessionLayer(project=proj)
        pinned_blocks = l1.get_pinned_blocks(project=proj)
        hits = l1.search("architecture convention pattern decision rule invariant", limit=3)
        recent_hits = [h.text for h in hits]

        ep = EpisodicLayer(project=proj)
        recent_sessions = ep.get_timeline(project=proj, limit=3)
        if recent_sessions:
            session_count = len(recent_sessions)
            episodic_recap = EpisodicLayer.format_briefing(recent_sessions)
        # Register new active session
        ep.start_session(project=proj)
    except Exception:
        pass

    # Freshness probe: instant cached answer, network (if due) in background.
    # Never blocks session start and never raises.
    fresh_line = ""
    try:
        try:
            from agi_memory import sync as _sync
        except ImportError:
            import sync as _sync
        fresh_line = _sync.format_freshness_line(_sync.ensure_fresh_background())
    except Exception:
        pass

    if not pinned_blocks and not recent_hits and not episodic_recap and not fresh_line:
        return

    output: List[str] = []
    output.append(f"<!-- AGENT_MEMORY_STARTUP_CONTEXT -->")
    output.append(f"# Agent Memory: Active Context & Precedents ({proj})")

    if episodic_recap:
        header = "## Prior Session Briefing" if session_count == 1 else f"## Recent Sessions (Last {session_count})"
        output.append(f"\n{header}")
        output.append(episodic_recap)

    if pinned_blocks:
        output.append("\n## Pinned Core Memory (Active Invariants)")
        for b in pinned_blocks:
            k = b.get("block_key", "")
            cat = b.get("category", "system")
            c = b.get("content", "")
            output.append(f"- **[{k}]** ({cat}): {c}")

    if recent_hits:
        output.append("\n## Top Project Precedents")
        for h in recent_hits:
            output.append(f"- {_clip(h)}")

    if fresh_line:
        output.append("\n## Vault Sync")
        output.append(f"- {fresh_line}")

    output.append("\n*Query `memory_recall` (epistemic), `memory_timeline` (episodic), or `code_structure` (code graph) for additional context.*")
    output.append(f"<!-- AGENT_MEMORY_STARTUP_CONTEXT_END -->")

    print("\n".join(output))


def hook_pre_compact(project: Optional[str] = None) -> None:
    """PreCompact: Curate high-signal working memory into L2 knowledge graph before context loss."""
    proj = project or detect_project()
    sys.path.insert(0, str(REPO_DIR))
    try:
        try:
            from agi_memory import promote
        except ImportError:
            import promote
        promoted = promote.auto_promote(limit=10, project=proj)
        if promoted:
            print(f"[agent-memory] PreCompact: Curated {len(promoted)} durable item(s) to knowledge graph.")
    except Exception:
        pass


def hook_session_end(project: Optional[str] = None) -> None:
    """SessionEnd / Stop: Finalize episodic session, commit vault, and trigger background sync."""
    proj = project or detect_project()
    sys.path.insert(0, str(REPO_DIR))
    try:
        try:
            from agi_memory.layers.episodic_layer import EpisodicLayer
        except ImportError:
            from layers.episodic_layer import EpisodicLayer
        ep = EpisodicLayer(project=proj)
        ep.end_session(project=proj)
    except Exception:
        pass

    try:
        try:
            from agi_memory import sync
        except ImportError:
            import sync
        res = sync.sync(push=True, pull=True)
        if res.get("status") == "ok":
            print("[agent-memory] SessionEnd: Synced memory vault with remote.")
    except Exception:
        pass


def hook_pre_commit() -> None:
    """Git pre-commit: Verify test suite and offline invariants."""
    sys.path.insert(0, str(REPO_DIR))
    val_script = Path.cwd() / "hooks" / "validate-offline.sh"
    if not val_script.exists():
        val_script = REPO_DIR.parent.parent / "hooks" / "validate-offline.sh"
    if val_script.exists() and os.access(val_script, os.X_OK):
        ret = subprocess.call([str(val_script)], **hidden_subprocess_kwargs())
        if ret != 0:
            sys.exit(ret)
        return

    # Fallback to tests/test_offline.py
    test_script = Path.cwd() / "tests" / "test_offline.py"
    if not test_script.exists():
        test_script = REPO_DIR.parent.parent / "tests" / "test_offline.py"
    if test_script.exists():
        py = detect_python()
        ret = subprocess.call([py, str(test_script)], **hidden_subprocess_kwargs())
        if ret != 0:
            sys.exit(ret)


def hook_post_commit(project: Optional[str] = None) -> None:
    """Git post-commit: Record commit into session & episodic memory, incrementally index code graph."""
    proj = project or detect_project()
    sys.path.insert(0, str(REPO_DIR))

    try:
        log_out = subprocess.check_output(
            ["git", "log", "-1", "--pretty=format:%h%x1f%s%x1f%b"],
            stderr=subprocess.DEVNULL,
            text=True,
            **hidden_subprocess_kwargs()
        ).strip()
        if not log_out:
            return
        parts = log_out.split("\x1f")
        cid = parts[0]
        subject = parts[1] if len(parts) > 1 else ""
        body = parts[2].strip() if len(parts) > 2 else ""

        # Filter low-signal commits (e.g. merge, wip, bump)
        ignore_patterns = r"^(merge |wip|bump version|update changelog|temp)"
        if re.search(ignore_patterns, subject, re.I):
            return

        text = f"Commit {cid}: {subject}"
        if body:
            text += f"\n{body}"

        category = "decision"
        if re.search(r"\b(fix|bug|resolve|patch)\b", subject, re.I):
            category = "bugfix"
        elif re.search(r"\b(arch|refactor|design|layer)\b", subject, re.I):
            category = "architecture"
        elif re.search(r"\b(pattern|convention|rule)\b", subject, re.I):
            category = "pattern"

        try:
            from agi_memory.layers.session_layer import SessionLayer
            from agi_memory.layers.episodic_layer import EpisodicLayer
            from agi_memory.layers.code_layer import CodeLayer
        except ImportError:
            from layers.session_layer import SessionLayer
            from layers.episodic_layer import EpisodicLayer
            from layers.code_layer import CodeLayer

        l1 = SessionLayer(project=proj)
        l1.record(text=text, title=f"Git commit: {subject[:50]}", project=proj, category=category)

        # Record into episodic history
        try:
            ep = EpisodicLayer(project=proj)
            last_sess = ep.get_last_session(project=proj)
            sid = last_sess["session_id"] if last_sess else "active"
            ep.record_event(
                session_id=sid,
                event_type="commit",
                summary=f"Commit {cid}: {subject}",
                details={"hash": cid, "subject": subject},
                project=proj
            )
        except Exception:
            pass

        # Incrementally update structural code graph
        try:
            diff_files = subprocess.check_output(
                ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", cid],
                stderr=subprocess.DEVNULL,
                text=True,
                **hidden_subprocess_kwargs()
            ).splitlines()
            if diff_files:
                cl = CodeLayer(project=proj)
                for df in diff_files:
                    f_path = Path(df.strip())
                    if f_path.is_file():
                        cl.index_file(f_path, project=proj)
        except Exception:
            pass

    except Exception:
        pass


# ============================================================================
# Hook Generation and Installation Helpers
# ============================================================================

def generate_shell_wrappers(hooks_dir: Path, py_path: str, repo_dir: Path) -> Dict[str, Path]:
    """Generate universal shell wrappers in ~/.agent-memory/hooks/."""
    hooks_dir.mkdir(parents=True, exist_ok=True)
    scripts = {
        "session-start": f"""#!/usr/bin/env bash
exec "{py_path}" "{repo_dir / 'hooks.py'}" session-start "$@"
""",
        "pre-compact": f"""#!/usr/bin/env bash
exec "{py_path}" "{repo_dir / 'hooks.py'}" pre-compact "$@"
""",
        "session-end": f"""#!/usr/bin/env bash
exec "{py_path}" "{repo_dir / 'hooks.py'}" session-end "$@"
""",
        "pre-commit": f"""#!/usr/bin/env bash
exec "{py_path}" "{repo_dir / 'hooks.py'}" pre-commit "$@"
""",
        "post-commit": f"""#!/usr/bin/env bash
exec "{py_path}" "{repo_dir / 'hooks.py'}" post-commit "$@"
""",
    }

    created = {}
    for name, content in scripts.items():
        p = hooks_dir / f"{name}.sh"
        p.write_text(content, encoding="utf-8")
        try:
            p.chmod(0o755)
        except Exception:
            pass
        created[name] = p

    return created


# ============================================================================
# Assistant-Specific Hook Integrations
# ============================================================================

def install_claude_hooks(scope: str = "user", py_path: str = None) -> Tuple[bool, str]:
    """Install SessionStart, PreCompact, and SessionEnd hooks for Claude Code."""
    py = py_path or detect_python()
    hooks_py = Path(__file__).resolve()
    settings_path = Path.home() / ".claude" / "settings.json" if scope == "user" else Path.cwd() / ".claude" / "settings.json"

    data: Dict[str, Any] = {}
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    hooks = data.setdefault("hooks", {})

    cmd_start = f'"{py}" "{hooks_py}" session-start'
    cmd_compact = f'"{py}" "{hooks_py}" pre-compact'
    cmd_end = f'"{py}" "{hooks_py}" session-end'

    def _is_memory_hook(entry: Dict[str, Any]) -> bool:
        return any(
            "hooks.py" in h.get("command", "")
            or "agent-memory" in h.get("command", "")
            or "agi-memory" in h.get("command", "")
            or "agi-hooks" in h.get("command", "")
            for h in entry.get("hooks", [])
        )

    # Purge any previous or stale memory hooks to eliminate duplicates or broken paths
    for ev in ("SessionStart", "PreCompact", "SessionEnd"):
        if ev in hooks:
            hooks[ev] = [e for e in hooks[ev] if not _is_memory_hook(e)]

    def _ensure_hook(event: str, cmd: str, matcher: Optional[str] = None):
        event_list = hooks.setdefault(event, [])
        new_entry: Dict[str, Any] = {
            "hooks": [
                {
                    "type": "command",
                    "command": cmd
                }
            ]
        }
        if matcher:
            new_entry["matcher"] = matcher
        event_list.append(new_entry)

    _ensure_hook("SessionStart", cmd_start, matcher="startup|resume|clear|compact")
    _ensure_hook("PreCompact", cmd_compact)
    _ensure_hook("SessionEnd", cmd_end)

    # Sanitize and ensure Claude Code permission format (mcp__<server>__*)
    perms = data.get("permissions", {})
    if isinstance(perms, dict) and "allow" in perms and isinstance(perms["allow"], list):
        fixed_allow = []
        for rule in perms["allow"]:
            if rule in ("mcp:agent-memory:*", "mcp:agi-memory:*"):
                if "mcp__agent-memory__*" not in fixed_allow:
                    fixed_allow.append("mcp__agent-memory__*")
                if "mcp__agi-memory__*" not in fixed_allow:
                    fixed_allow.append("mcp__agi-memory__*")
            else:
                fixed_allow.append(rule)
        perms["allow"] = fixed_allow

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True, f"Installed Claude Code hooks in {settings_path}"


def uninstall_claude_hooks(scope: str = "user") -> Tuple[bool, str]:
    settings_path = Path.home() / ".claude" / "settings.json" if scope == "user" else Path.cwd() / ".claude" / "settings.json"
    if not settings_path.exists():
        return True, "No settings file found"
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return False, "Failed to parse settings.json"

    hooks = data.get("hooks", {})
    for event in list(hooks.keys()):
        cleaned = []
        for entry in hooks[event]:
            has_agent_mem = any("hooks.py" in h.get("command", "") or "agent-memory" in h.get("command", "") for h in entry.get("hooks", []))
            if not has_agent_mem:
                cleaned.append(entry)
        if cleaned:
            hooks[event] = cleaned
        else:
            del hooks[event]

    settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True, f"Uninstalled Claude Code hooks from {settings_path}"


def install_agy_hooks(scope: str = "user", py_path: str = None) -> Tuple[bool, str]:
    """Install PreInvocation and Stop hooks for Antigravity (agy)."""
    py = py_path or detect_python()
    hooks_py = REPO_DIR / "hooks.py"
    hooks_path = Path.home() / ".gemini" / "config" / "hooks.json" if scope == "user" else Path.cwd() / ".agents" / "hooks.json"

    data: Dict[str, Any] = {}
    if hooks_path.exists():
        try:
            data = json.loads(hooks_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    cmd_start = f'"{py}" "{hooks_py}" session-start'
    cmd_end = f'"{py}" "{hooks_py}" session-end'

    data["agent-memory"] = {
        "enabled": True,
        "PreInvocation": [
            {
                "type": "command",
                "command": cmd_start
            }
        ],
        "Stop": [
            {
                "type": "command",
                "command": cmd_end
            }
        ]
    }

    hooks_path.parent.mkdir(parents=True, exist_ok=True)
    hooks_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True, f"Installed Antigravity hooks in {hooks_path}"


def uninstall_agy_hooks(scope: str = "user") -> Tuple[bool, str]:
    hooks_path = Path.home() / ".gemini" / "config" / "hooks.json" if scope == "user" else Path.cwd() / ".agents" / "hooks.json"
    if not hooks_path.exists():
        return True, "No hooks file found"
    try:
        data = json.loads(hooks_path.read_text(encoding="utf-8"))
    except Exception:
        return False, "Failed to parse hooks.json"

    if "agent-memory" in data:
        del data["agent-memory"]
        hooks_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True, f"Uninstalled Antigravity hooks from {hooks_path}"


# ============================================================================
# OpenCode Plugin (OpenCode has no native hook config; hooks ship as a plugin)
# ============================================================================

# OpenCode loads every .js/.ts file in these dirs at startup; the plugin shells
# out to this same hooks.py via Bun's built-in shell, so no npm deps needed.
# @@PY@@ / @@HOOKS_PY@@ are replaced at install time (plain replace, not
# format(), so the JS braces survive).
OPENCODE_PLUGIN_TEMPLATE = """\
// agent-memory lifecycle plugin for OpenCode.
// Generated by `agi-integrate install opencode` - reinstall to refresh paths.
// Zero npm dependencies: shells out to the stdlib-only hooks CLI.
//
// Mapping:
//   session-start -> experimental.chat.system.transform (once per session)
//   pre-compact   -> experimental.session.compacting (output.context)
//   session-end   -> event session.idle (fire-and-forget; sync is idempotent)
//
// Known gaps: --continue/--resume fires no bus event, so a resumed session
// keeps whatever context it already has. session.idle fires per turn; the
// first one ends the episodic session, later ones only re-sync.
export const AgentMemoryPlugin = async ({ $ }) => {
  const PY = "@@PY@@";
  const HOOKS_PY = "@@HOOKS_PY@@";
  const seen = new Set();

  const run = async (verb) => {
    try {
      return (await $`${PY} ${HOOKS_PY} ${verb}`.text()).trim();
    } catch {
      return "";
    }
  };

  return {
    // Mutate output.system IN PLACE (push/splice); reassigning the array is
    // a silent no-op on the OpenCode side.
    "experimental.chat.system.transform": async (input, output) => {
      const id = (input && input.sessionID) || "default";
      if (seen.has(id)) return;
      seen.add(id);
      const ctx = await run("session-start");
      if (ctx) output.system.push(ctx);
    },
    "experimental.session.compacting": async (input, output) => {
      const msg = await run("pre-compact");
      if (msg) output.context.push(msg);
    },
    event: async ({ event }) => {
      if (event && event.type === "session.idle") {
        await run("session-end");
      }
    },
  };
};
"""


def opencode_plugin_path(scope: str = "user") -> Path:
    """Target path of the agent-memory OpenCode plugin file."""
    if scope == "user":
        base = Path(os.environ.get("XDG_CONFIG_HOME", "").strip() or Path.home() / ".config")
        return base.expanduser() / "opencode" / "plugins" / "agent-memory.js"
    return Path.cwd() / ".opencode" / "plugins" / "agent-memory.js"


def install_opencode_plugin(scope: str = "user", py_path: str = None) -> Tuple[bool, str]:
    """Write the agent-memory lifecycle plugin for OpenCode."""
    py = py_path or detect_python()
    hooks_py = str(Path(__file__).resolve())
    target = opencode_plugin_path(scope)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        content = OPENCODE_PLUGIN_TEMPLATE.replace("@@PY@@", py).replace("@@HOOKS_PY@@", hooks_py)
        target.write_text(content, encoding="utf-8")
        return True, f"Installed OpenCode plugin in {target}"
    except OSError as e:
        return False, f"Failed to write OpenCode plugin: {e}"


def uninstall_opencode_plugin(scope: str = "user") -> Tuple[bool, str]:
    """Remove the agent-memory OpenCode plugin file (only if ours)."""
    target = opencode_plugin_path(scope)
    if not target.exists():
        return True, "No OpenCode plugin file found"
    try:
        if "AgentMemoryPlugin" not in target.read_text(encoding="utf-8"):
            return False, f"Refusing to remove foreign plugin file {target}"
        target.unlink()
        return True, f"Uninstalled OpenCode plugin from {target}"
    except OSError as e:
        return False, f"Failed to remove OpenCode plugin: {e}"


def install_git_hooks(target_dir: Path | None = None, py_path: str = None) -> Tuple[bool, str]:
    """Install pre-commit, post-commit, and pre-push hooks in .git/hooks/."""
    root = target_dir or Path.cwd()
    git_dir = root / ".git"
    if not git_dir.exists():
        return False, f"No .git repository found in {root}"

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    py = py_path or detect_python()
    hooks_py = REPO_DIR / "hooks.py"

    pre_commit_content = f"""#!/usr/bin/env bash
# agent-memory pre-commit hook
"{py}" "{hooks_py}" pre-commit
"""
    post_commit_content = f"""#!/usr/bin/env bash
# agent-memory post-commit hook
"{py}" "{hooks_py}" post-commit &
"""
    pre_push_content = f"""#!/usr/bin/env bash
# agent-memory pre-push hook
"{py}" "{hooks_py}" session-end &
"""

    def _write_hook(name: str, content: str):
        hp = hooks_dir / name
        if hp.exists():
            curr = hp.read_text(encoding="utf-8")
            if "agent-memory" in curr:
                return
            content = curr.rstrip() + "\n\n" + content
        hp.write_text(content, encoding="utf-8")
        try:
            hp.chmod(0o755)
        except Exception:
            pass

    _write_hook("pre-commit", pre_commit_content)
    _write_hook("post-commit", post_commit_content)
    _write_hook("pre-push", pre_push_content)

    return True, f"Installed Git hooks in {hooks_dir}"


def uninstall_git_hooks(target_dir: Path | None = None) -> Tuple[bool, str]:
    root = target_dir or Path.cwd()
    git_dir = root / ".git"
    if not git_dir.exists():
        return True, "No .git directory"

    hooks_dir = git_dir / "hooks"
    for name in ["pre-commit", "post-commit", "pre-push"]:
        hp = hooks_dir / name
        if hp.exists():
            try:
                lines = hp.read_text(encoding="utf-8").splitlines()
                filtered = [l for l in lines if "hooks.py" not in l and "agent-memory" not in l]
                has_meaningful_code = any(l.strip() and not l.startswith("#!") for l in filtered)
                if has_meaningful_code:
                    hp.write_text("\n".join(filtered) + "\n", encoding="utf-8")
                else:
                    hp.unlink()
            except Exception:
                pass
    return True, f"Uninstalled Git hooks from {hooks_dir}"


def install_all_hooks(scope: str = "user", py_path: str = None) -> Dict[str, Tuple[bool, str]]:
    """Install lifecycle hooks across all detected and supported assistants and git."""
    py = py_path or detect_python()
    ensure_hooks_dir()
    generate_shell_wrappers(DEFAULT_HOOKS_DIR, py, REPO_DIR)

    results: Dict[str, Tuple[bool, str]] = {}
    results["claude"] = install_claude_hooks(scope=scope, py_path=py)
    results["agy"] = install_agy_hooks(scope=scope, py_path=py)
    results["opencode"] = install_opencode_plugin(scope=scope, py_path=py)

    git_res = install_git_hooks(py_path=py)
    if git_res[0]:
        results["git"] = git_res

    return results


def uninstall_all_hooks(scope: str = "user") -> Dict[str, Tuple[bool, str]]:
    results: Dict[str, Tuple[bool, str]] = {}
    results["claude"] = uninstall_claude_hooks(scope=scope)
    results["agy"] = uninstall_agy_hooks(scope=scope)
    results["opencode"] = uninstall_opencode_plugin(scope=scope)
    results["git"] = uninstall_git_hooks()
    return results


# ============================================================================
# Main Entry Point
# ============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="agent-memory-hooks",
        description="Lifecycle hook dispatcher and installer for agent-memory."
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    # Lifecycle event commands
    p_start = subparsers.add_parser("session-start", help="Inject active context and precedents")
    p_start.add_argument("--project", "-p", help="Project name override")

    p_compact = subparsers.add_parser("pre-compact", help="Promote high-signal L1 memories before compaction")
    p_compact.add_argument("--project", "-p", help="Project name override")

    p_end = subparsers.add_parser("session-end", help="Commit vault and trigger background Git sync")
    p_end.add_argument("--project", "-p", help="Project name override")

    subparsers.add_parser("pre-commit", help="Verify offline test suite before commit")
    
    p_post_commit = subparsers.add_parser("post-commit", help="Record commit summary to session memory")
    p_post_commit.add_argument("--project", "-p", help="Project name override")

    # Hook installation management
    p_install = subparsers.add_parser("install", help="Install lifecycle hooks for tools")
    p_install.add_argument("tools", nargs="*", default=["all"], help="Tool names (claude, agy, opencode, git, all)")
    p_install.add_argument("--scope", choices=["user", "project"], default="user", help="Scope: user or project")
    p_install.add_argument("--python", help="Override Python executable path")

    p_uninstall = subparsers.add_parser("uninstall", help="Uninstall lifecycle hooks for tools")
    p_uninstall.add_argument("tools", nargs="*", default=["all"], help="Tool names (claude, agy, opencode, git, all)")
    p_uninstall.add_argument("--scope", choices=["user", "project"], default="user", help="Scope: user or project")

    args = parser.parse_args()

    if args.action == "session-start":
        hook_session_start(getattr(args, "project", None))
    elif args.action == "pre-compact":
        hook_pre_compact(getattr(args, "project", None))
    elif args.action == "session-end":
        hook_session_end(getattr(args, "project", None))
    elif args.action == "pre-commit":
        hook_pre_commit()
    elif args.action == "post-commit":
        hook_post_commit(getattr(args, "project", None))
    elif args.action == "install":
        tools = [t.lower() for t in args.tools]
        if "all" in tools:
            res = install_all_hooks(scope=args.scope, py_path=args.python)
            for k, (ok, msg) in res.items():
                print(f"[{'✓' if ok else '✗'}] {k:10}: {msg}")
        else:
            for t in tools:
                if t in ("claude", "claude-code"):
                    ok, msg = install_claude_hooks(scope=args.scope, py_path=args.python)
                elif t in ("agy", "antigravity"):
                    ok, msg = install_agy_hooks(scope=args.scope, py_path=args.python)
                elif t == "opencode":
                    ok, msg = install_opencode_plugin(scope=args.scope, py_path=args.python)
                elif t == "git":
                    ok, msg = install_git_hooks(py_path=args.python)
                else:
                    ok, msg = False, f"Unknown hook tool: {t}"
                print(f"[{'✓' if ok else '✗'}] {t:10}: {msg}")
    elif args.action == "uninstall":
        tools = [t.lower() for t in args.tools]
        if "all" in tools:
            res = uninstall_all_hooks(scope=args.scope)
            for k, (ok, msg) in res.items():
                print(f"[{'✓' if ok else '✗'}] {k:10}: {msg}")
        else:
            for t in tools:
                if t in ("claude", "claude-code"):
                    ok, msg = uninstall_claude_hooks(scope=args.scope)
                elif t in ("agy", "antigravity"):
                    ok, msg = uninstall_agy_hooks(scope=args.scope)
                elif t == "opencode":
                    ok, msg = uninstall_opencode_plugin(scope=args.scope)
                elif t == "git":
                    ok, msg = uninstall_git_hooks()
                else:
                    ok, msg = False, f"Unknown hook tool: {t}"
                print(f"[{'✓' if ok else '✗'}] {t:10}: {msg}")


if __name__ == "__main__":
    main()
