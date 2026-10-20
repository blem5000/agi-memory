"""Automatic sync freshness checks: file-remote fixtures, no network.

Builds a bare git repo as a local "remote" so behind/ahead detection,
background convergence and offline degradation are testable offline.
Isolates sync.json via monkeypatched SYNC_CONFIG_FILE.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agi_memory import sync


def _git(args, cwd):
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, (args, p.stderr)
    return p.stdout.strip()


def _make_vault_with_remote(tmp, name):
    """Vault repo with a bare local repo as origin, pushed and clean."""
    origin = Path(tmp) / f"{name}.git"
    _git(["init", "--bare", str(origin)], cwd=tmp)
    work = Path(tmp) / name
    work.mkdir()
    _git(["init"], cwd=work)
    _git(["config", "user.email", "t@t"], cwd=work)
    _git(["config", "user.name", "t"], cwd=work)
    (work / "records.jsonl").write_text('{"a": 1}\n', encoding="utf-8")
    _git(["add", "-A"], cwd=work)
    _git(["commit", "-m", "init"], cwd=work)
    _git(["branch", "-M", "main"], cwd=work)
    _git(["remote", "add", "origin", str(origin)], cwd=work)
    _git(["push", "-u", "origin", "main"], cwd=work)
    return work, origin


with tempfile.TemporaryDirectory() as tmp:
    # Isolate global sync config for this process AND detached workers (env is inherited)
    os.environ["AGI_MEMORY_SYNC_CONFIG_FILE"] = str(Path(tmp) / "sync.json")

    work, origin = _make_vault_with_remote(tmp, "vault")

    # In sync: fresh clone state
    f = sync.check_freshness(vault_dir=work, do_fetch=True)
    assert f["state"] == "in_sync" and f["behind"] == 0 and f["ahead"] == 0, f

    # Remote moves ahead by 1 (simulating the other machine's push)
    other = Path(tmp) / "other"
    _git(["clone", str(origin), str(other)], cwd=tmp)
    _git(["checkout", "main"], cwd=other)
    _git(["config", "user.email", "t@t"], cwd=other)
    _git(["config", "user.name", "t"], cwd=other)
    (other / "records.jsonl").write_text('{"a": 1}\n{"b": 2}\n', encoding="utf-8")
    _git(["add", "-A"], cwd=other)
    _git(["commit", "-m", "other machine"], cwd=other)
    _git(["push", "origin", "main"], cwd=other)

    f = sync.check_freshness(vault_dir=work, do_fetch=True)
    assert f["state"] == "behind" and f["behind"] == 1 and f["ahead"] == 0, f

    # Cached (no-fetch) read reports the same without network
    fc = sync.check_freshness(vault_dir=work, do_fetch=False)
    assert fc["behind"] == 1, fc

    # Local commit on top -> diverged
    (work / "local.txt").write_text("mine\n", encoding="utf-8")
    _git(["add", "-A"], cwd=work)
    _git(["commit", "-m", "mine"], cwd=work)
    f = sync.check_freshness(vault_dir=work, do_fetch=True)
    assert f["state"] == "diverged" and f["behind"] == 1 and f["ahead"] == 1, f

    # Background ensure converges (pull --rebase + push) and reports cached instantly
    os.environ["AGI_MEMORY_SYNC_CHECK_INTERVAL"] = "1"
    cfg = sync.load_sync_config()
    cfg["last_check_epoch"] = 0
    sync.save_sync_config(cfg)
    t0 = time.time()
    cached = sync.ensure_fresh_background(vault_dir=work)
    assert time.time() - t0 < 5, "ensure_fresh_background must return instantly"
    assert cached["state"] == "diverged", cached
    for _ in range(100):
        st = sync.check_freshness(vault_dir=work, do_fetch=False)
        if st["state"] == "in_sync":
            break
        time.sleep(0.2)
    else:
        raise AssertionError(f"background sync did not converge: {st}")
    del os.environ["AGI_MEMORY_SYNC_CHECK_INTERVAL"]

    # Interval gate: fresh check just ran -> returns cached, no thread storm
    c2 = sync.ensure_fresh_background(vault_dir=work)
    assert c2["state"] == "in_sync", c2

    # Broken remote degrades to offline, never raises
    _git(["remote", "set-url", "origin", str(Path(tmp) / "nonexistent.git")], cwd=work)
    f = sync.check_freshness(vault_dir=work, do_fetch=True)
    assert f["state"] == "offline", f

    # No remote at all
    _git(["remote", "remove", "origin"], cwd=work)
    f = sync.check_freshness(vault_dir=work, do_fetch=True)
    assert f["state"] == "no_remote", f

    # Agent-facing line formatting
    assert "2 commit(s) behind" in sync.format_freshness_line({"state": "behind", "behind": 2, "ahead": 0})
    assert "not yet pushed" in sync.format_freshness_line({"state": "ahead", "behind": 0, "ahead": 3})
    assert "offline" in sync.format_freshness_line({"state": "offline", "behind": 0, "ahead": 0}).lower()
    assert sync.format_freshness_line({"state": "in_sync", "behind": 0, "ahead": 0}) == ""
    assert sync.format_freshness_line(None) == ""

    # sync_status carries cached freshness without network
    st = sync.sync_status()
    assert "behind" in st and "ahead" in st and "last_check_state" in st, st

    del os.environ["AGI_MEMORY_SYNC_CONFIG_FILE"]

print("test_sync_freshness: OK")
