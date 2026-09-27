"""Day-1 import of native assistant session history (no deja required).

`deja_import` distills transcripts with an LLM and is the better importer when
it is installed. It is not always: this reads the transcripts Claude Code, Codex
and OpenCode already wrote to disk, so a fresh vault is never empty.

No LLM here, so a session's L1 digest is its own words -- goal, the prompts
that drove it, files touched -- not a distillation. That is enough for
`memory_recall` to answer "have we been here before"; reach for deja-import
when a summary of what was decided is what you need.

Idempotent: episodic rows are keyed `{harness}:{session_id}`, and L1 skips any
session whose short id already appears in a title.
Usage:
    python3 -m agi_memory.history_import --index          # all sessions -> episodic
    python3 -m agi_memory.history_import --limit 20       # recent -> L1 digests
    agi-memory history-import --harness codex --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List

try:
    from agi_memory.layers.session_layer import SessionLayer
except ImportError:
    try:
        from layers.session_layer import SessionLayer
    except ImportError:
        from .layers.session_layer import SessionLayer

try:
    from agi_memory.deja_import import classify_category
except ImportError:  # pragma: no cover - only when the package layout is flat
    try:
        from deja_import import classify_category
    except ImportError:
        def classify_category(title: str, ctx: str) -> str:
            return "decision"

# ponytail: reads whole transcript files line by line, no size cap; a 200 MB
# rollout would be slow. Cap per-file bytes if a harness starts writing those.
MAX_PROMPTS = 6
PROMPT_CHARS = 400
DIGEST_CHARS = 3000

# Harness-injected turns arrive as the first "user" message of a session and
# say nothing about the work: Codex opens with <recommended_plugins>, Claude
# with <command-name>. Same reasoning as hooks._HARNESS_TURN.
_BOILERPLATE = ("<", "# agents.md", "you are codex", "you are claude")


def _home() -> Path:
    return Path.home()


def _opencode_db(explicit: str | None = None) -> Path | None:
    if explicit:
        # An explicit path that is not there is an answer, not a reason to read
        # some other database the caller did not ask for.
        return Path(explicit) if Path(explicit).exists() else None
    base = Path(os.environ.get("XDG_DATA_HOME", "").strip()
                or _home() / ".local" / "share") / "opencode" / "opencode.db"
    return base if base.exists() else None


def map_project(path: str) -> str:
    """A cwd or directory string -> project name (`/a/b/agi-memory` -> `agi-memory`)."""
    text = (path or "").strip().rstrip("/")
    return Path(text).name if text else "global"


def _real_prompt(text: str) -> str:
    return "" if text.lstrip().lower().startswith(_BOILERPLATE) else text.strip()


def _iso(value: Any) -> str:
    """Epoch seconds, epoch millis, or an ISO string -> ISO string (or '')."""
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        secs = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(secs, tz=timezone.utc).isoformat()
    return str(value)


def _jsonl(path: Path) -> Iterator[dict]:
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    yield row
    except OSError:
        return


def _text_of(content: Any) -> str:
    """A message body as plain text: str, or a list of {type,text} blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("text"))
    return ""


# --------------------------------------------------------------------------
# Per-harness readers. Each yields {"id","project","goal","started","ended",
# "touched","prompts"} -- the shape import_index/import_sessions consume.
# --------------------------------------------------------------------------

def codex_sessions(root: Path | None = None, limit: int = 50) -> List[Dict[str, Any]]:
    """`~/.codex/sessions/**/rollout-*.jsonl`: meta line + user turns."""
    base = Path(root) if root else _home() / ".codex" / "sessions"
    files = sorted(base.glob("**/rollout-*.jsonl"), key=lambda p: p.stat().st_mtime,
                   reverse=True)[:limit] if base.exists() else []
    out = []
    for f in files:
        sid = cwd = started = ended = ""
        prompts: List[str] = []
        for row in _jsonl(f):
            payload = row.get("payload") or {}
            ended = row.get("timestamp") or ended
            if row.get("type") == "session_meta":
                sid = payload.get("session_id") or payload.get("id") or sid
                cwd = payload.get("cwd") or cwd
                started = row.get("timestamp") or started
            elif (row.get("type") == "response_item" and payload.get("type") == "message"
                    and payload.get("role") == "user"):
                text = _real_prompt(_text_of(payload.get("content")))
                if text and len(prompts) < MAX_PROMPTS:
                    prompts.append(text[:PROMPT_CHARS])
        if sid:
            out.append({"id": sid, "project": map_project(cwd), "harness": "codex",
                        "goal": (prompts[0] if prompts else "codex session")[:500],
                        "started": started, "ended": ended, "touched": [],
                        "prompts": prompts})
    return out


def claude_sessions(root: Path | None = None, limit: int = 50) -> List[Dict[str, Any]]:
    """`~/.claude/projects/<slug>/<session>.jsonl`: ai-title + user turns."""
    base = Path(root) if root else _home() / ".claude" / "projects"
    files = sorted(base.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime,
                   reverse=True)[:limit] if base.exists() else []
    out = []
    for f in files:
        sid = f.stem
        cwd = title = started = ended = ""
        prompts: List[str] = []
        for row in _jsonl(f):
            kind = row.get("type")
            ended = row.get("timestamp") or ended
            if not started:
                started = row.get("timestamp") or ""
            sid = row.get("sessionId") or sid
            cwd = row.get("cwd") or cwd
            if kind == "ai-title":
                title = row.get("aiTitle") or title
            elif kind == "user":
                text = _real_prompt(_text_of((row.get("message") or {}).get("content")))
                if text and len(prompts) < MAX_PROMPTS:
                    prompts.append(text[:PROMPT_CHARS])
        if sid:
            out.append({"id": sid, "project": map_project(cwd), "harness": "claude",
                        "goal": (title or (prompts[0] if prompts else "claude session"))[:500],
                        "started": started, "ended": ended, "touched": [],
                        "prompts": prompts})
    return out


def opencode_sessions(db_path: str | None = None, limit: int = 50) -> List[Dict[str, Any]]:
    """`opencode.db` session table, read-only. Titles and file counts are already
    columns there, so this never touches the 3.8k-row part table."""
    db = _opencode_db(db_path)
    if not db:
        return []
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        rows = con.execute("""
            SELECT id, directory, title, summary_files, time_created, time_updated
            FROM session WHERE directory IS NOT NULL ORDER BY time_created DESC LIMIT ?
        """, (limit,)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    out = []
    for sid, directory, title, summary_files, created, updated in rows:
        try:
            touched = json.loads(summary_files or "[]")
            if not isinstance(touched, list):
                touched = []
        except ValueError:
            touched = []
        goal = (title or "opencode session").strip()
        out.append({"id": sid, "project": map_project(directory), "harness": "opencode",
                    "goal": goal[:500], "started": _iso(created), "ended": _iso(updated),
                    "touched": [str(t) for t in touched][:50], "prompts": [goal[:PROMPT_CHARS]]
                    if goal else []})
    return out


READERS = {"codex": codex_sessions, "claude": claude_sessions, "opencode": opencode_sessions}


def list_sessions(harness: str = "all", limit: int = 50, **kwargs) -> List[Dict[str, Any]]:
    """Newest-first sessions from one harness or all of them. Unreadable
    harnesses contribute nothing instead of failing the import."""
    names = list(READERS) if harness in ("all", "", None) else [harness]
    rows: List[Dict[str, Any]] = []
    for name in names:
        reader = READERS.get(name)
        if not reader:
            continue
        try:
            rows.extend(reader(limit=limit, **kwargs) if name == "opencode"
                        else reader(limit=limit))
        except (OSError, ValueError, sqlite3.Error):
            continue
    rows.sort(key=lambda r: r.get("ended") or r.get("started") or "", reverse=True)
    return rows[:limit]


def _digest(s: Dict[str, Any]) -> str:
    touched = s.get("touched") or []
    lines = [f"Imported from {s['harness']} session {s['id']}"
             f" ({s.get('ended') or s.get('started') or 'date unknown'})."]
    if touched:
        lines.append(f"Touched: {', '.join(touched[:8])}")
    lines.append(f"\nGoal: {s.get('goal', '')}")
    prompts = s.get("prompts") or []
    if len(prompts) > 1:
        lines.append("\nWhat was asked:")
        lines += [f"- {p[:200]}" for p in prompts[1:]]
    return "\n".join(lines)[:DIGEST_CHARS]


def import_index(harness: str = "all", limit: int = 0, project: str | None = None,
                 db_path=None) -> Dict[str, Any]:
    """Backfill session metadata into episodic history. No L1, no prompts: one
    row per session so old work stays findable after the transcripts move."""
    try:
        from agi_memory.layers.episodic_layer import EpisodicLayer
    except ImportError:
        try:
            from layers.episodic_layer import EpisodicLayer
        except ImportError:
            from .layers.episodic_layer import EpisodicLayer
    sessions = list_sessions(harness, limit or 100000)
    if project:
        sessions = [s for s in sessions if s["project"] == project]
    ep = EpisodicLayer(project="global", db_path=db_path)
    indexed = 0
    for s in sessions:
        if ep.upsert_imported(f"{s['harness']}:{s['id']}", s["project"], goal=s["goal"],
                              started_at=s.get("started"), ended_at=s.get("ended"),
                              touched_files=s.get("touched")):
            indexed += 1
    return {"listed": len(sessions), "indexed": indexed}


def import_sessions(harness: str = "all", limit: int = 20, project: str | None = None,
                    min_prompts: int = 1, dry_run: bool = False,
                    db_path=None) -> Dict[str, Any]:
    """Import session digests into L1 (origin="history-import")."""
    sessions = list_sessions(harness, limit)
    if project:
        sessions = [s for s in sessions if s["project"] == project]
    l1 = SessionLayer(project="global", db_path=db_path)
    seen = " ".join(o["title"].lower() for o in l1.list_observations(limit=2000))
    imported, skipped, ids = 0, 0, []
    for s in sessions:
        short = s["id"][:8].lower()
        if short in seen or len(s.get("prompts") or []) < min_prompts:
            skipped += 1
            continue
        if dry_run:
            imported += 1
            continue
        rec = l1.record(text=_digest(s), title=f"[{s['harness']}:{short}] {s['goal'][:80]}",
                        project=s["project"],
                        category=classify_category(s["goal"], _digest(s)),
                        origin="history-import")
        if rec.get("id"):
            imported += 1
            ids.append(rec["id"])
        else:
            skipped += 1
    return {"listed": len(sessions), "imported": imported, "skipped": skipped, "ids": ids}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="agi-memory history-import",
                                description="Import native assistant session history "
                                            "(claude/codex/opencode) with no deja required")
    p.add_argument("--harness", default="all", choices=["all", *READERS])
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--project", default=None)
    p.add_argument("--index", action="store_true",
                   help="Backfill every session's metadata into episodic history (no L1)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    if args.index:
        res = import_index(harness=args.harness, limit=args.limit, project=args.project)
    else:
        res = import_sessions(harness=args.harness, limit=args.limit,
                              project=args.project, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(res, indent=2))
    elif args.index:
        print(f"[✓] Indexed {res['indexed']} sessions into episodic history "
              f"({res['listed']} listed).")
    elif args.dry_run:
        print(f"[dry-run] {res['listed']} sessions, {res['imported']} importable, "
              f"{res['skipped']} skipped.")
    elif res["imported"] == 0:
        print(f"[✓] Nothing new ({res['listed']} listed, {res['skipped']} skipped).")
    else:
        print(f"[✓] Imported {res['imported']} sessions ({res['skipped']} skipped).")


if __name__ == "__main__":
    main()
