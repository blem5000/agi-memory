"""OpenCode plugin template: the installed v2 hook-API contract (no OpenCode run)."""
import _isolate  # noqa: F401,E402 -- must run before agi_memory resolves any path
import os
import sys
import tempfile
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agi_memory import hooks

T = hooks.OPENCODE_PLUGIN_TEMPLATE

# The module must export a plugin function: OpenCode imports the file and calls
# whatever `Plugin` is, so the old `{ id, setup(ctx) }` object was silently dead.
assert "export const AgiMemoryPlugin = async (" in T, "plugin is not an exported async function"
assert "export default AgiMemoryPlugin;" in T
for dead in ("ctx.session.hook", "setup(ctx)", "ctx.event.subscribe"):
    assert dead not in T, f"removed OpenCode API still present: {dead}"

# Every lifecycle verb, mapped to a hook the installed API actually calls.
for hook in ("chat.message", "experimental.chat.system.transform", "tool.execute.after",
             "experimental.session.compacting", "event"):
    assert hook in T, f"hook not wired: {hook}"
# dotted names are not identifiers, so they must be quoted keys in the returned object
for hook in ("chat.message", "experimental.chat.system.transform", "tool.execute.after",
             "experimental.session.compacting"):
    assert f'"{hook}": async' in T, f"hook not a returned key: {hook}"
assert "tool.execute.before\":" not in T, "pre-tool recall has no context channel"

for verb in ("session-start", "user-prompt-submit", "post-tool", "pre-compact", "session-end"):
    assert f'"{verb}"' in T, f"verb not dispatched: {verb}"

# OpenCode tool names are lowercase; hooks.py matches Claude-style names and
# reads the file path from tool_input.file_path.
for low, high in (("bash", "Bash"), ("edit", "Edit"), ("write", "Write"), ("read", "Read")):
    assert f'{low}: "{high}"' in T, f"tool name unmapped: {low} -> {high}"
assert "file_path" in T and "filePath" in T

# Zero npm dependencies: node:child_process is the only import.
assert T.count("import ") == 1 and 'from "node:child_process"' in T

# Paths stay placeholders until install substitutes them.
assert "@@PY@@" in T and "@@HOOKS_PY@@" in T

with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp) / "home"
    old_home, old_xdg = os.environ.get("HOME"), os.environ.pop("XDG_CONFIG_HOME", None)
    os.environ["HOME"] = str(home)
    try:
        ok, msg = hooks.install_opencode_plugin(scope="user", py_path="/usr/bin/python3")
        assert ok, msg
        target = home / ".config" / "opencode" / "plugins" / "agi-memory.js"
        assert target.exists(), f"plugin not written: {target}"
        installed = target.read_text(encoding="utf-8")
    finally:
        os.environ["HOME"] = old_home or ""
        if old_xdg is not None:
            os.environ["XDG_CONFIG_HOME"] = old_xdg

assert '"@@PY@@"' not in installed and '"@@HOOKS_PY@@"' not in installed
assert '"@@' not in installed
assert 'const PY = "/usr/bin/python3";' in installed
assert f'const HOOKS_PY = "{Path(hooks.__file__).resolve()}";' in installed
for hook in ("chat.message", "experimental.chat.system.transform", "tool.execute.after",
             "experimental.session.compacting", "event"):
    assert hook in installed, f"installed plugin lost hook: {hook}"
assert "AgiMemoryPlugin" in installed

print("test_opencode_plugin: OK")
