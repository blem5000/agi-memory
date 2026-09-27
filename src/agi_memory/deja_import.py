"""Day-1 import of deja session history into agi-memory L1 (stdlib only).

deja already indexes every coding session on this machine (7311+ across
claude/codex/opencode/hermes/...) as raw transcripts. agi-memory curates
decisions with rationale, supersession and pins. This module bridges them:
each deja session's distilled digest (`deja ctx <id>`) becomes one L1
observation with origin="deja-import", so a fresh vault starts full and
recall works from moment zero.

Idempotent: skips sessions whose deja short-id is already in a title.
Usage:
    python3 -m agi_memory.deja_import --limit 50 --dry-run
    agi-memory deja-import --project my-app --since 30d
    agi-bootstrap --repo . --with-deja
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
from typing import Any, Callable, Dict, List, Optional

try:
    from agi_memory.layers.session_layer import SessionLayer
except ImportError:
    try:
        from layers.session_layer import SessionLayer
    except ImportError:
        from .layers.session_layer import SessionLayer

# honey: O(n) ctx subprocess per session; fine under ~200 imports, batch or cache if grown.
CTX_CHAR_CAP = 2000

_CATEGORY_HINTS = (
    (("fix", "bug", "error", "crash", "regression", "hotfix"), "bugfix"),
    (("architect", "refactor", "breaking", "migrat", "schema"), "architecture"),
    (("convention", "style", "lint", "rule", "policy"), "convention"),
    (("how to", "pattern", "recipe", "workflow"), "pattern"),
)


def classify_category(title: str, ctx: str) -> str:
    blob = f"{title}\n{ctx[:500]}".lower()
    for hints, cat in _CATEGORY_HINTS:
        if any(h in blob for h in hints):
            return cat
    return "decision"


def find_deja_bin(explicit: str | None = None) -> Optional[str]:
    """Locate the deja binary: explicit path, PATH, then ~/.local/bin fallback."""
    for cand in (explicit, shutil.which("deja")):
        if cand and Path(cand).exists():
            return cand
    fallback = Path.home() / ".local" / "bin" / "deja"
    return str(fallback) if fallback.exists() else None


def _strip_prefix(raw: str) -> str:
    """Drop deja's `deja: ...` notice lines; JSON starts at the first '{'."""
    start = raw.find("{")
    return raw[start:] if start >= 0 else raw


def _parse_first_json(raw: str) -> dict:
    """Parse the first JSON value, ignoring deja notice lines before/after it."""
    try:
        return json.JSONDecoder().raw_decode(_strip_prefix(raw))[0]
    except json.JSONDecodeError:
        return {}


def _run(bin_path: str, args: List[str], timeout: int = 60) -> str:
    res = subprocess.run([bin_path] + args, capture_output=True, text=True, timeout=timeout)
    return (res.stdout or "") + ("\n" + res.stderr if res.stderr else "")


def list_sessions(bin_path: str, limit: int = 50, project: str | None = None,
                  harness: str | None = None, since: str | None = None,
                  runner: Callable[..., str] = _run) -> List[Dict[str, Any]]:
    """Newest-first session metas via `deja last N --json`."""
    args = ["last", str(limit), "--json"]
    if project:
        args += ["--project", project]
    if harness:
        args += ["--harness", harness]
    if since:
        args += ["--since", since]
    try:
        return _parse_first_json(runner(bin_path, args)).get("sessions", [])
    except AttributeError:
        return []


def get_ctx(bin_path: str, session_id: str,
            runner: Callable[..., str] = _run) -> str:
    """Distilled markdown digest for one session; '' when unavailable."""
    out = runner(bin_path, ["ctx", session_id], timeout=90)
    lines = [ln for ln in out.splitlines() if not ln.startswith("deja: ")]
    text = "\n".join(lines).strip()
    return "" if len(text) < 200 else text[:CTX_CHAR_CAP]


def map_project(deja_project: str) -> str:
    """`ca-statement-processor/ca-statement-processor` -> `ca-statement-processor`."""
    return (deja_project or "").split("/")[-1].strip() or "global"


def import_index(limit: int = 0, project: str | None = None,
                 harness: str | None = None, since: str | None = None,
                 all_sessions: bool = False, deja_bin: str | None = None,
                 db_path=None,
                 runner: Callable[..., str] = _run) -> dict:
    """Backfill every deja session's metadata into episodic history (no ctx calls).

    One subprocess lists the index; one row per session, idempotent on the
    deja session id. Old work stays findable after deja is gone; recent
    high-signal sessions still deserve import_sessions() digests into L1.
    """
    try:
        from agi_memory.layers.episodic_layer import EpisodicLayer
    except ImportError:
        try:
            from layers.episodic_layer import EpisodicLayer
        except ImportError:
            from .layers.episodic_layer import EpisodicLayer
    bin_path = find_deja_bin(deja_bin)
    if not bin_path:
        return {"error": "deja binary not found", "listed": 0, "indexed": 0}
    args = ["last", str(100000 if (all_sessions or not limit) else limit)]
    if project:
        args += ["--project", project]
    if harness:
        args += ["--harness", harness]
    if since:
        args += ["--since", since]
    args.append("--json")
    sessions = _parse_first_json(runner(bin_path, args)).get("sessions", [])
    ep = EpisodicLayer(project="global", db_path=db_path)
    indexed = 0
    for s in sessions:
        sid = s.get("id", "")
        if not sid:
            continue
        goal = (s.get("title") or "untitled")[:500]
        if ep.upsert_imported(
                f"deja:{sid}", map_project(s.get("project", "")),
                goal=goal, started_at=s.get("started"), ended_at=s.get("updated"),
                touched_files=s.get("touched") or []):
            indexed += 1
    return {"listed": len(sessions), "indexed": indexed}


def import_sessions(limit: int = 50, project: str | None = None,
                    harness: str | None = None, since: str | None = None,
                    min_words: int = 800, dry_run: bool = False,
                    deja_bin: str | None = None, db_path=None,
                    runner: Callable[..., str] = _run) -> dict:
    """Import deja digests into L1. Returns counts + created ids."""
    bin_path = find_deja_bin(deja_bin)
    if not bin_path:
        return {"error": "deja binary not found", "listed": 0,
                "imported": 0, "skipped": 0, "ids": []}
    sessions = list_sessions(bin_path, limit, project, harness, since, runner)
    l1 = SessionLayer(project="global", db_path=db_path)
    existing = {o["title"].lower() for o in l1.list_observations(limit=2000)}
    imported, skipped, ids = 0, 0, []
    for s in sessions:
        sid = s.get("id", "")
        short = sid[:8]
        title = (s.get("title") or "untitled").strip()
        if not sid or short.lower() in str(existing) or (s.get("words") or 0) < min_words:
            skipped += 1
            continue
        ctx = get_ctx(bin_path, sid, runner)
        if not ctx:
            skipped += 1
            continue
        proj = map_project(s.get("project", "") if not project else project)
        full_title = f"[deja:{short}] {title[:80]}"
        touched = (s.get("touched") or [])[:8]
        text = (f"Imported from deja session {sid} "
                f"({s.get('harness', '?')}, updated {s.get('updated', '?')}).\n"
                + (f"Touched: {', '.join(touched)}\n" if touched else "")
                + f"\n{ctx}")
        if dry_run:
            imported += 1
            continue
        rec = l1.record(text=text[:3000], title=full_title, project=proj,
                        category=classify_category(title, ctx), origin="deja-import")
        if rec.get("id"):
            imported += 1
            ids.append(rec["id"])
            existing.add(full_title.lower())
        else:
            skipped += 1
    return {"listed": len(sessions), "imported": imported,
            "skipped": skipped, "ids": ids}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="agi-memory deja-import",
                                description="Import deja session digests into L1")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--project", default=None)
    p.add_argument("--harness", default=None)
    p.add_argument("--since", default=None, help="e.g. 30d, 12h")
    p.add_argument("--min-words", type=int, default=800)
    p.add_argument("--deja-bin", default=None)
    p.add_argument("--full", action="store_true",
                   help="Also backfill every session's metadata into episodic history")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    if args.full:
        i_res = import_index(limit=args.limit, project=args.project, harness=args.harness,
                             since=args.since, all_sessions=True, deja_bin=args.deja_bin)
        if args.json:
            print(json.dumps({"index": i_res}, indent=2))
        elif i_res.get("error"):
            print(f"[!] {i_res['error']}")
        else:
            print(f"[✓] Indexed {i_res['indexed']} sessions into episodic history "
                  f"({i_res['listed']} listed).")
        return
    res = import_sessions(limit=args.limit, project=args.project, harness=args.harness,
                          since=args.since, min_words=args.min_words,
                          dry_run=args.dry_run, deja_bin=args.deja_bin)
    if args.json:
        print(json.dumps(res, indent=2))
    elif res.get("error"):
        print(f"[!] {res['error']}")
    elif args.dry_run:
        print(f"[dry-run] {res['listed']} sessions, {res['imported']} importable, {res['skipped']} skipped.")
    elif res["imported"] == 0:
        print(f"[✓] Nothing new ({res['listed']} listed, {res['skipped']} skipped).")
    else:
        print(f"[✓] Imported {res['imported']} deja sessions ({res['skipped']} skipped).")


if __name__ == "__main__":
    main()
