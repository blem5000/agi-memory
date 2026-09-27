"""Point-of-action recall: command logging, error follow-ups, friction, hooks (offline)."""
import _isolate  # noqa: F401,E402 -- must run before agi_memory resolves any path
import io
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agi_memory.layers.episodic_layer import EpisodicLayer, looks_destructive


def _ep(proj="shop"):
    # Default (isolated) store: hooks resolve the same DB, so seeded rows are visible to them.
    return EpisodicLayer(project=proj)


# destructive filter (deja fix rule)
assert looks_destructive("git push --force origin main")
assert looks_destructive("rm -rf /tmp/x")
assert looks_destructive("git merge feature")
assert not looks_destructive("pytest tests/ -q")
assert not looks_destructive("gh run watch 123 --exit-status")

# upsert_imported is idempotent
ep = _ep()
assert ep.upsert_imported("deja:aaa", "shop", goal="Fix webhooks",
                          started_at="2026-01-01", touched_files=["/x/a.py"]) is True
assert ep.upsert_imported("deja:aaa", "shop", goal="Fix webhooks") is False

# error -> fix pairing across a session (failure carries the error output)
ep.start_session(session_id="s1", project="shop")
ep.record_event("s1", "command", "pytest tests/ -q",
                {"command": "pytest tests/ -q", "exit": 1,
                 "error": "failed tests/test_auth.py assert false"}, project="shop")
ep.record_event("s1", "command", "pytest tests/test_auth.py -q",
                {"command": "pytest tests/test_auth.py -q", "exit": 0}, project="shop")
f = ep.error_followups("failed tests/test_auth.py assert false", project="shop")
assert f and f[0]["command"] == "pytest tests/test_auth.py -q", f

# destructive follow-ups are never suggested
ep.start_session(session_id="s2", project="shop")
ep.record_event("s2", "command", "go build ./...",
                {"command": "go build ./...", "exit": 1}, project="shop")
ep.record_event("s2", "command", "rm -rf /tmp/build",
                {"command": "rm -rf /tmp/build", "exit": 0}, project="shop")
assert ep.error_followups("go build ./...", project="shop") == []

# short signatures never match (no false positives)
assert ep.error_followups("err", project="shop") == []

# recent_commands: ok_only + binary prefix
ep.record_event("s2", "command", "go vet ./...",
                {"command": "go vet ./...", "exit": 0}, project="shop")
rc = ep.recent_commands("go", project="shop", limit=5)
assert {r["command"] for r in rc} == {"go vet ./..."}, rc
rc_all = ep.recent_commands("go", project="shop", limit=5, ok_only=False)
assert len(rc_all) == 2, rc_all

# friction: same failure in 3 sessions surfaces; passes and loners do not
for sid in ("f1", "f2", "f3"):
    ep.start_session(session_id=sid, project="shop")
    ep.record_event(sid, "command", "docker compose up",
                    {"command": "docker compose up", "exit": 1}, project="shop")
ep.start_session(session_id="f4", project="shop")
ep.record_event("f4", "command", "docker compose up",
                {"command": "docker compose up", "exit": 0}, project="shop")
ep.record_event("f4", "command", "make once-failing",
                {"command": "make once-failing", "exit": 1}, project="shop")
fr = ep.failed_command_stats(project="shop", min_sessions=3)
assert len(fr) == 1 and fr[0]["signature"].startswith("docker compose"), fr

# hooks: post-tool logs + suggests; pre-tool silent on miss
sys.path.insert(0, str(_SRC / "agi_memory"))
import hooks as H

ep.start_session(session_id="hs", project="shop")
H._read_hook_payload = lambda: {"session_id": "hs", "tool_name": "Bash",
                                "tool_input": {"command": "pytest tests/ -q"},
                                "tool_response": "FAILED tests/test_auth.py\nassert False"}
buf = io.StringIO()
with redirect_stdout(buf):
    H.hook_post_tool.__wrapped__ if hasattr(H.hook_post_tool, "__wrapped__") else H.hook_post_tool("shop")
out = buf.getvalue()
assert "After this error before" in out and "test_auth" in out, out

H._read_hook_payload = lambda: {"session_id": "hs", "tool_name": "Bash",
                                "tool_input": {"command": "brand-new-binary --flag"}}
buf = io.StringIO()
with redirect_stdout(buf):
    H.hook_pre_tool("shop")
assert buf.getvalue() == "", repr(buf.getvalue())

print("[✓] point-of-action checks passed")
