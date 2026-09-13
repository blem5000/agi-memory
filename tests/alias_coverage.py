"""Measure how much of the real vocabulary the entity-alias table actually covers.

Backlog #4 says synonym recall is reachable only for pairs already in the alias
table, and that nobody has measured whether that table covers the words people
actually write. Assuming it does is how item 4 got marked closed the first time.

This reads the recorded memories on this machine, ranks the terms that really
occur in them, and reports what fraction of that vocabulary the table can map.
It is a measurement, not a gate: it prints and exits 0, because a low number is
the finding, not a build failure.

Run:  python3 tests/alias_coverage.py [--db PATH] [--top 40]
"""
import argparse
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agi_memory.config import get_default_db  # noqa: E402
from agi_memory.layers.base import open_db  # noqa: E402
from agi_memory.layers.session_layer import STOPWORDS  # noqa: E402
from agi_memory.layers.graph_layer import GraphLayer  # noqa: E402

# Words that are frequent in any technical corpus and carry no entity identity,
# so counting them as "uncovered vocabulary" would only flatter or damn the
# number without saying anything about synonyms.
GENERIC = {
    "the", "and", "for", "with", "that", "this", "from", "into", "when", "then",
    "code", "file", "files", "line", "lines", "used", "using", "use", "add",
    "added", "adds", "fix", "fixed", "fixes", "new", "old", "run", "runs",
    "make", "made", "set", "get", "not", "now", "one", "two", "all", "any",
    "was", "were", "has", "have", "had", "can", "will", "would", "should",
    "test", "tests", "commit", "change", "changes", "changed", "project",
}


def terms_in_memories(db_path: Path) -> Counter:
    """Rank the words that actually appear in recorded memories."""
    counts: Counter = Counter()
    try:
        con = open_db(db_path, readonly=True)
    except sqlite3.Error as e:
        print(f"cannot open {db_path}: {e}")
        return counts
    try:
        rows = con.execute("SELECT title, narrative FROM observations").fetchall()
    except sqlite3.Error:
        rows = []
    con.close()
    for title, narrative in rows:
        blob = f"{title or ''} {narrative or ''}".lower()
        for tok in re.findall(r"[a-z][a-z0-9_]{2,}", blob):
            if tok in STOPWORDS or tok in GENERIC:
                continue
            counts[tok] += 1
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=None, help="Database to measure (default: this machine's)")
    ap.add_argument("--top", type=int, default=40, help="How many uncovered terms to list")
    args = ap.parse_args()

    db_path = Path(args.db) if args.db else Path(get_default_db())
    if not db_path.exists():
        print(f"no memory database at {db_path}; nothing to measure")
        return 0

    counts = terms_in_memories(db_path)
    if not counts:
        print(f"no observations in {db_path}; nothing to measure")
        return 0

    gl = GraphLayer(db_path=db_path)
    aliases = {k.lower(): v for k, v in gl.list_aliases().items()}
    # A term is reachable if it is an alias, or if it is the canonical form
    # something else maps onto -- both mean a synonym query can land on it.
    canonicals = {v.lower() for v in aliases.values()}
    reachable = set(aliases) | canonicals

    distinct = len(counts)
    total = sum(counts.values())
    hit_distinct = sum(1 for t in counts if t in reachable)
    hit_weighted = sum(c for t, c in counts.items() if t in reachable)

    print(f"database        : {db_path}")
    print(f"alias entries   : {len(aliases)}")
    print(f"distinct terms  : {distinct}")
    print(f"term occurrences: {total}")
    print()
    print(f"coverage, distinct terms : {hit_distinct}/{distinct} = "
          f"{100.0 * hit_distinct / distinct:.1f}%")
    print(f"coverage, by frequency   : {hit_weighted}/{total} = "
          f"{100.0 * hit_weighted / total:.1f}%")
    print()
    print(f"Top {args.top} frequent terms the table cannot map "
          f"(each is a synonym query that will miss):")
    shown = 0
    for term, n in counts.most_common():
        if term in reachable:
            continue
        print(f"  {n:>4}x  {term}")
        shown += 1
        if shown >= args.top:
            break
    if not shown:
        print("  (none)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
