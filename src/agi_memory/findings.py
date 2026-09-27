"""Findings: evidence attached to recalled memories, for the agent to judge.

There is deliberately no contradiction detector here. Deciding that two memories
disagree is a judgement call, and a rule that makes it will be wrong in ways
nobody sees -- so the finding is the *evidence* and the conclusion stays with the
agent reading it.

Two things that sound like they belong here do not, and the reasons are worth
keeping:

  - "these two memories contradict each other". Measuring it first: the
    concepts column is boilerplate ("decision", "pattern") plus canonical terms,
    and grouping live memories by shared concept terms groups them by the word
    "works" or "solution" -- 318 groups, all noise. Grouping by title prefix
    gave 1,046 groups, which are near-duplicate commit records, not subject
    peers. There is no reliable mechanical signal for "same subject" in this
    data, let alone for "disagrees".

  - "this memory is stale because it is old". Age is not validity. "Port 8080
    is required behind the proxy" is true for years, and decay demotes exactly
    the load-bearing facts.

What is left is mechanical and checkable, and every finding is scoped to the
memories a recall actually returned, so the cost is proportional to the answer
rather than to the store.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, Iterable, List, Optional

MAX_FINDINGS = 4
FINDING_CHARS = 300
# Surfaced this many times with nothing downstream ever citing it.
SUSPICIOUS_SHOWS = 3
OLD_DAYS = 180
DAY_MS = 86400 * 1000


def _load_usage(db_path) -> Dict[int, Dict[str, Any]]:
    """shown counts per observation id, from the read-receipt table."""
    from agi_memory.layers.base import open_db
    out: Dict[int, Dict[str, Any]] = {}
    if not db_path.exists():
        return out
    try:
        con = open_db(db_path, readonly=True)
    except Exception:
        return out
    try:
        for h, n, last in con.execute(
                "SELECT content_hash, shown_count, last_shown_at FROM memory_usage"):
            out[h] = {"shown": n, "last": last}
    except Exception:
        return out
    finally:
        con.close()
    return out


def _cited_ids(db_path) -> set:
    """Observation ids some later record has cited or superseded."""
    from agi_memory.layers.base import open_db
    cited: set = set()
    if not db_path.exists():
        return cited
    try:
        con = open_db(db_path, readonly=True)
    except Exception:
        return cited
    try:
        for (raw,) in con.execute(
                "SELECT supersedes_refs FROM observations "
                "WHERE supersedes_refs IS NOT NULL AND supersedes_refs != '[]'"):
            try:
                for ref in json.loads(raw):
                    cited.add(str(ref).lstrip("#"))
            except (ValueError, TypeError, AttributeError):
                continue
    except Exception:
        pass
    finally:
        con.close()
    return cited


def _missing_files(db_path, project: Optional[str], paths: Iterable[str]):
    """Indexed files from `paths` that no longer exist.

    Root-aware: `missing_paths` only judges files the code graph indexed, so a
    reference to a file that was never indexed is not reported as missing. That
    is the right way round -- an unindexed path is unknown, not gone, and
    calling it gone would be a claim the index cannot support.
    """
    try:
        from agi_memory.layers.code_layer import CodeLayer
        cl = CodeLayer(project=project, db_path=db_path)
        return {p for p in cl.missing_paths(set(paths), project) if p}
    except Exception:
        return set()


def for_observations(ids: Iterable[str], project: Optional[str] = None,
                     db_path=None) -> List[str]:
    """Findings for the observations a recall just returned.

    Each line states what was observed and what to check. None of them asserts
    that a memory is wrong.
    """
    from agi_memory.layers.base import open_db
    from agi_memory.layers.session_layer import SessionLayer
    if not db_path:
        from agi_memory.config import get_default_db
        db_path = get_default_db()
    ids = [str(i) for i in ids if str(i).isdigit()]
    if not ids or not db_path.exists():
        return []
    ph = ",".join("?" for _ in ids)
    try:
        con = open_db(db_path, readonly=True)
    except Exception:
        return []
    try:
        rows = con.execute(
            f"SELECT id, title, origin, files_modified, created_at_epoch, content_hash "
            f"FROM observations WHERE id IN ({ph})", ids).fetchall()
    except Exception:
        return []
    finally:
        con.close()
    if not rows:
        return []

    usage = _load_usage(db_path)
    cited = _cited_ids(db_path)
    now = int(time.time() * 1000)
    findings: List[str] = []

    for oid, title, origin, files_raw, epoch, chash in rows:
        oid = str(oid)
        shown = (usage.get(chash) or {}).get("shown", 0)
        # 1. The claim points at code that is no longer there. This is the only
        #    finding that can be checked rather than suspected, and it is the
        #    reason the code graph earns its keep in a memory layer.
        try:
            files = json.loads(files_raw or "[]")
        except (ValueError, TypeError):
            files = []
        if isinstance(files, list) and files:
            # No "/" requirement: a top-level reference like "CLAUDE.md" is a
            # perfectly ordinary file. What gets dropped is the placeholder text
            # importers write when a transcript did not actually say.
            real = [f.strip() for f in files
                    if isinstance(f, str) and f.strip()
                    and not f.strip().lower().startswith("not specified")]
            gone = _missing_files(db_path, project, real)
            if gone:
                names = ", ".join(sorted(gone)[:3])
                findings.append(
                    f"#{oid} references {len(gone)} file(s) that no longer exist: {names}. "
                    f"Check its claim against the current code.")
        # 2. An inference that keeps being served and is never confirmed.
        if origin == "agent-inferred" and shown >= SUSPICIOUS_SHOWS and oid not in cited:
            findings.append(
                f"#{oid} is an agent inference, surfaced {shown}x and never confirmed by a "
                f"later record. Verify before relying on it.")
        # 3. Load-bearing and old. Not an invalidation -- a prompt to look.
        if shown >= SUSPICIOUS_SHOWS and epoch and (now - epoch) > OLD_DAYS * DAY_MS:
            days = int((now - epoch) / DAY_MS)
            findings.append(
                f"#{oid} was written {days} days ago and has been surfaced {shown}x. "
                f"High-traffic and old -- worth re-checking.")
    return findings[:MAX_FINDINGS]


def render(findings: List[str]) -> str:
    """The block appended to a recall response. Empty when there is nothing."""
    if not findings:
        return ""
    body = "\n".join(f"- {f[:FINDING_CHARS]}" for f in findings)
    return ("\n\n## findings (evidence, not verdicts -- decide what to do with them)\n"
            + body)
