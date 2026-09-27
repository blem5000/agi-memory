"""Promote durable knowledge L1 -> L2. Reads claude-mem SQLite directly
(zero tokens, no worker needed), keeps only durable signals, dedupes via
state file. Pass any object with .add(text) as l2 (GraphLayer or fake).
"""
import hashlib
import json
import os
import sqlite3
from pathlib import Path

try:
    from agi_memory.config import get_default_db, get_state_path
    from agi_memory.layers.base import open_db
except ImportError:
    from config import get_default_db, get_state_path
    from layers.base import open_db

DB = get_default_db()
STATE = get_state_path()
DURABLE_TYPES = {"decision", "bugfix", "feature"}
DURABLE_CONCEPTS = {"why-it-exists", "pattern", "gotcha", "trade-off", "how-it-works"}
import re as _re
NO_SIGNAL = _re.compile(
    r"^(none[\s,]*)+$|no (?:new |technical )*(patterns|learnings|work|changes)|"
    r"nothing (new|learned)|not (yet |currently )?(identified|performed|introduced)|"
    r"no work has been performed", _re.I)


def _signal(body: str) -> bool:
    return len(body) >= 60 and not NO_SIGNAL.search(body)


def _load_state() -> set:
    return set(json.loads(STATE.read_text())) if STATE.exists() else set()


def _save_state(seen: set) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(sorted(seen)))


def _attribution(origin: str | None, agent: str | None) -> str:
    """`[user-confirmed by host:1234] ` prefix, or '' for the default case.

    Only the two cases that change how a reader should treat the fact are
    labelled. An unattributed line would read as plain fact, so the interesting
    cases have to be visible in the durable copy rather than only in the ledger.
    """
    o = (origin or "").strip()
    who = (agent or "").strip()
    if o == "user-confirmed":
        return f"[{o}{' by ' + who if who else ''}] "
    if o in ("bootstrapped", "deja-import", "history-import"):
        return f"[{o}, unverified] "
    if who:
        return f"[{o or 'agent-inferred'} by {who}] "
    return ""


def _concepts(raw: str | None) -> set:
    """Concept tags from the `concepts` column.

    It holds a JSON array, so splitting it on commas yields '["decision"' and
    ' "pattern"]' -- neither of which equals 'pattern', so the durable-concept
    gate below never matched anything. collect() returned an empty list on every
    real database and the L2 graph was never populated by promotion at all;
    tests/eval_l2.py missed it by ingesting its own fixtures instead of calling
    this. Falls back to a comma split so a pre-JSON value still reads.
    """
    text = (raw or "").strip()
    if not text:
        return set()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except ValueError:
            return set()
        if isinstance(parsed, list):
            return {str(c).strip() for c in parsed}
    return {t.strip() for t in text.split(",") if t.strip()}


def collect(project: str | None = None, since_epoch: int = 0) -> list:
    """(text, source_ref) pairs. source_ref is "obs:<id>" for promoted
    observations and None for session learnings, which have no row."""
    if not DB.exists():
        return []
    # The observations table gains columns by migration, and a migration only
    # runs when a SessionLayer is built. collect() is a plain reader, so on a
    # database written by an older version its query hits "no such column" --
    # which the except below turns into "nothing to promote". That is how a
    # populated L1 ended up promoting nothing at all, with no error anywhere.
    try:
        try:
            from agi_memory.layers.session_layer import SessionLayer
        except ImportError:
            from layers.session_layer import SessionLayer
        SessionLayer(db_path=DB)
    except Exception:
        pass
    con = open_db(DB, readonly=True)
    out: list[str] = []
    try:
        q = "SELECT project, learned, completed FROM session_summaries WHERE created_at_epoch > ?"
        args: list = [since_epoch]
        if project:
            q += " AND project = ?"
            args.append(project)
        for proj, learned, completed in con.execute(q, args).fetchall():
            body = " ".join(p for p in (learned, completed) if p and p != "None").strip()
            if _signal(body):
                out.append((f"[{proj}] session learning: {body}", None))
    except sqlite3.OperationalError:
        pass
    try:
        q = ("SELECT project, title, facts, concepts, id, origin, agent FROM observations "
             "WHERE created_at_epoch > ? AND type IN ('decision','bugfix','feature')")
        args = [since_epoch]
        if project:
            q += " AND project = ?"
            args.append(project)
        for proj, title, facts, concepts, obs_id, origin, agent in con.execute(q, args).fetchall():
            tags = _concepts(concepts)
            if tags & DURABLE_CONCEPTS and facts:
                # obs:<id> is the provenance handle a hard delete uses to find
                # what this observation promoted into the graph.
                #
                # The tag travels with the text because this is the copy every
                # agent retrieves forever. L1 keeps origin and agent in columns
                # that promotion dropped on the floor, so a durable fact could
                # not say whether a human confirmed it or one agent inferred it.
                out.append((f"[{proj}] {title}: {_attribution(origin, agent)}{facts}",
                            f"obs:{obs_id}"))
    except sqlite3.OperationalError:
        pass
    con.close()
    return out


def promote(l2, project: str | None = None, since_epoch: int = 0,
            limit: int | None = None) -> list[str]:
    seen = _load_state()
    # collect() yields (text, source_ref); older callers only ever saw the text,
    # so the return value stays a list of strings.
    fresh = [(t, ref) for t, ref in collect(project, since_epoch)
             if hashlib.sha1(t.encode()).hexdigest() not in seen]
    if limit is not None:
        fresh = fresh[:limit]
    for text, source_ref in fresh:
        try:
            l2.add(text, source_ref=source_ref)
        except TypeError:
            # Any L2 implementing the older add(text) signature still works;
            # it just cannot participate in cascade deletes.
            l2.add(text)
        seen.add(hashlib.sha1(text.encode()).hexdigest())
    _save_state(seen)
    return [t for t, _ in fresh]


def auto_promote(limit: int = 25, project: str | None = None) -> list[str]:
    """Automated knowledge graph promotion for hooks, compaction, and CLI."""
    try:
        candidates = collect(project=project)
        if not candidates:
            return []
        try:
            from agi_memory.layers.graph_layer import GraphLayer
        except ImportError:
            from layers.graph_layer import GraphLayer
        l2 = GraphLayer(db_path=DB, project=project)
        return promote(l2, project=project, limit=limit)
    except Exception:
        return []


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Promote durable knowledge from L1 to L2.")
    parser.add_argument("--project", "-p", default=None, help="Filter by project name")
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="Preview candidates without invoking L2 or modifying state")
    parser.add_argument("--limit", "-l", type=int, default=None,
                        help="Max items to promote/preview")
    parser.add_argument("--auto", action="store_true",
                        help="Automated batch promotion mode (defaults limit to 25)")
    args = parser.parse_args(argv)

    if args.auto:
        batch_limit = args.limit if args.limit is not None else 25
        promoted = auto_promote(limit=batch_limit, project=args.project)
        print(f"Auto-promoted {len(promoted)} item(s) to knowledge graph.")
    else:
        seen = _load_state()
        candidates = [t for t, _ in collect(args.project)]
        fresh = [t for t in candidates if hashlib.sha1(t.encode()).hexdigest() not in seen]
        if args.limit:
            fresh = fresh[:args.limit]

        print(f"Total candidates: {len(candidates)} | Fresh (unpromoted): {len(fresh)}")
        if args.dry_run:
            preview_count = min(len(fresh), 5)
            if preview_count:
                print(f"\n[Dry Run] Showing {preview_count} sample candidate(s):")
                for idx, item in enumerate(fresh[:preview_count], 1):
                    print(f"  {idx}. {item[:140]}...")
            else:
                print("No fresh candidates found.")
        else:
            if not fresh:
                print("Nothing new to promote.")
            else:
                try:
                    from agi_memory.layers.graph_layer import GraphLayer
                except ImportError:
                    from layers.graph_layer import GraphLayer
                l2 = GraphLayer(db_path=DB, project=args.project)
                promoted = promote(l2, project=args.project, limit=args.limit)
                print(f"Successfully promoted {len(promoted)} item(s) to native knowledge graph.")


if __name__ == "__main__":
    main()
