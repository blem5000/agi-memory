"""deja-import checks: parsing, filtering, category, idempotency (offline, fake runner)."""
import _isolate  # noqa: F401,E402 -- must run before agi_memory resolves any path
import json
import sys
import tempfile
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agi_memory import deja_import as di

# The victory print below uses [✓]; on a cp1252 console that raises
# UnicodeEncodeError and masks a green run, so force UTF-8 like the CLI does.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# No deja binary on a clean machine: every test below runs against fake
# runners, so pin the lookup to a dummy path for the whole file.
di.find_deja_bin = lambda explicit=None: "/fake/deja"

_FAKE_LAST = {"schema_version": 2, "sessions": [
    {"id": "aaa11111-0000-0000-0000-000000000001", "harness": "claude",
     "project": "shop/shop", "title": "Fix webhook retry crash",
     "words": 5000, "updated": "2026-09-20", "touched": ["/x/a.py"]},
    {"id": "bbb22222-0000-0000-0000-000000000002", "harness": "codex",
     "project": "shop/shop", "title": "tiny note",
     "words": 50, "updated": "2026-09-21", "touched": []},
]}
_FAKE_CTX = ("# deja context\n## Problem\nWebhook retries crash after 5 attempts.\n"
             "## Solution\nCap at 5 with backoff, provider bans above.\n" + "detail. " * 100)


def _fake_runner(bin_path, args, timeout=60):
    if args[0] == "last":
        return "deja: notice line\n" + json.dumps(_FAKE_LAST)
    assert args[0] == "ctx"
    return "deja: notice\n" + _FAKE_CTX


def _trailing_notice_runner(bin_path, args, timeout=60):
    """Real deja shape: pure JSON on stdout, notices appended after."""
    if args[0] == "last":
        return json.dumps(_FAKE_LAST) + "\ndeja: 895 transcripts no longer on disk"
    return "deja: notice\n" + _FAKE_CTX


def _runner_no_ctx(bin_path, args, timeout=60):
    if args[0] == "last":
        return json.dumps(_FAKE_LAST)
    return "too short"


# prefix stripping + session listing (notices before AND after JSON)
got = di.list_sessions("/fake/deja", runner=_fake_runner)
assert len(got) == 2 and got[0]["id"].startswith("aaa11111"), got
got2 = di.list_sessions("/fake/deja", runner=_trailing_notice_runner)
assert len(got2) == 2, got2

# category + project mapping
assert di.classify_category("Fix webhook retry crash", _FAKE_CTX) == "bugfix"
assert di.classify_category("Architecture overview", "nothing special here") == "architecture"
assert di.map_project("ca-statement-processor/ca-statement-processor") == "ca-statement-processor"
assert di.map_project("") == "global"

# import: 1 in (big session), 1 skipped (tiny), empty ctx -> skip
with tempfile.TemporaryDirectory() as td:
    db = str(Path(td) / "mem.db")
    r1 = di.import_sessions(limit=10, db_path=db, runner=_fake_runner,
                            deja_bin="/fake/deja", min_words=800)
    assert r1 == {"listed": 2, "imported": 1, "skipped": 1, "ids": r1["ids"]} and len(r1["ids"]) == 1, r1
    # idempotent rerun imports nothing new
    r2 = di.import_sessions(limit=10, db_path=db, runner=_fake_runner,
                            deja_bin="/fake/deja", min_words=800)
    assert r2["imported"] == 0 and r2["skipped"] == 2, r2
    # recall finds it by keyword
    from agi_memory.layers.session_layer import SessionLayer
    hits = SessionLayer(project="shop", db_path=db).search("webhook", limit=5)
    assert hits, "imported deja memory not recallable"

# missing binary -> clean error, no crash
_orig_find = di.find_deja_bin
di.find_deja_bin = lambda explicit=None: None
try:
    r3 = di.import_sessions(deja_bin="/nonexistent/deja-xyz", runner=_fake_runner)
    # The message points at the native reader, which needs no binary at all.
    assert r3["error"].startswith("deja binary not found"), r3
    assert "history-import" in r3["error"], r3
finally:
    di.find_deja_bin = _orig_find

# short/empty ctx never records
r4 = di.import_sessions(limit=10, db_path=str(Path(tempfile.mkdtemp()) / "m2.db"),
                        runner=_runner_no_ctx, deja_bin="/fake/deja", min_words=1)
assert r4["imported"] == 0, r4

print("[✓] deja-import checks passed")
