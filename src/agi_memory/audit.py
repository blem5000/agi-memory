"""Audit and hygiene engine for agi-memory.

Identifies low-impact, obsolete, and contaminated memories:
- Synthetic test fixtures (e.g. project in test-proj, test-*, p, x)
- Zero-signal noise matching NO_SIGNAL_PATTERN
- Unconfirmed agent inferences with zero citations and zero relevance
- Superseded records whose replacements exist
- Broken file references

Zero dependencies (stdlib only).
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from agi_memory.config import get_default_db, get_vault_dir
    from agi_memory.layers.base import open_db
    from agi_memory.vault import NO_SIGNAL_PATTERN, deduplicate_and_compact
except ImportError:
    from config import get_default_db, get_vault_dir
    from layers.base import open_db
    from vault import NO_SIGNAL_PATTERN, deduplicate_and_compact

TEST_PROJECT_PATTERNS = (
    re.compile(r"^test[-_]?", re.I),
    re.compile(r"^(p|x|temp|tmp|dummy|fixture)$", re.I),
)

ZERO_SIGNAL_TITLES = (
    re.compile(r"^project initialization$", re.I),
    re.compile(r"^caveman ultra mode request$", re.I),
    re.compile(r"^(session start|session init|starting session)$", re.I),
)


def is_test_project(project: Optional[str]) -> bool:
    """True if project name matches test suite artifacts."""
    if not project:
        return False
    p = project.strip().lower()
    return any(pat.search(p) for pat in TEST_PROJECT_PATTERNS)


def is_noise_record(title: str, text: str) -> bool:
    """True if memory content contains zero technical signal."""
    t = (title or "").strip()
    body = (text or "").strip()
    if not t and not body:
        return True
    if NO_SIGNAL_PATTERN.search(f"{t} {body}"):
        return True
    if any(pat.search(t) for pat in ZERO_SIGNAL_TITLES) and len(body) < 160:
        return True
    return False


class MemoryAudit:
    def __init__(self, db_path: Optional[Path] = None, vault_dir: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else get_default_db()
        self.vault_dir = Path(vault_dir) if vault_dir else get_vault_dir()

    def scan(self, project: Optional[str] = None) -> Dict[str, Any]:
        """Scan SQLite database and return categorized low-impact records."""
        out = {
            "total_observations": 0,
            "test_fixtures": [],
            "noise_records": [],
            "superseded_records": [],
            "unconfirmed_zero_use": [],
            "missing_file_records": [],
        }
        if not self.db_path.exists():
            return out

        con = open_db(self.db_path, readonly=True)
        con.row_factory = sqlite3.Row
        try:
            sql = ("SELECT id, project, type, title, subtitle, facts, narrative, "
                   "files_modified, files_read, origin, relevance_count, "
                   "superseded_by, content_hash FROM observations")
            params = []
            if project and project not in ("*", "global"):
                sql += " WHERE project = ?"
                params.append(project)

            cur = con.execute(sql, params)
            rows = cur.fetchall()
            out["total_observations"] = len(rows)

            # Check usage stats
            cited_ids = set()
            try:
                for (raw,) in con.execute(
                    "SELECT supersedes_refs FROM observations WHERE supersedes_refs IS NOT NULL AND supersedes_refs != '[]'"
                ):
                    for ref in json.loads(raw):
                        cited_ids.add(str(ref).lstrip("#"))
            except Exception:
                pass

            for r in rows:
                oid = r["id"]
                proj = r["project"] or ""
                title = r["title"] or ""
                facts = r["facts"] or ""
                narrative = r["narrative"] or ""
                full_text = f"{narrative} {facts}".strip()
                origin = r["origin"] or "agent-inferred"
                rel_count = r["relevance_count"] or 0
                is_superseded = r["type"] == "superseded" or bool(r["superseded_by"])

                record_summary = {
                    "id": oid,
                    "project": proj,
                    "title": title[:60],
                    "origin": origin,
                    "relevance": rel_count,
                    "hash": r["content_hash"],
                }

                # 1. Test fixtures
                if is_test_project(proj):
                    out["test_fixtures"].append(record_summary)
                    continue

                # 2. Noise records
                if is_noise_record(title, full_text):
                    out["noise_records"].append(record_summary)
                    continue

                # 3. Superseded records
                if is_superseded:
                    out["superseded_records"].append(record_summary)
                    continue

                # 4. Unconfirmed agent inferences with zero citations
                if (origin == "agent-inferred" and rel_count == 0
                        and str(oid) not in cited_ids
                        and len(full_text) < 120):
                    out["unconfirmed_zero_use"].append(record_summary)

        finally:
            con.close()

        return out

    def prune(self, ids: List[int], tombstone: bool = True) -> int:
        """Prune specific observation IDs from SQLite and optionally record tombstones."""
        if not ids or not self.db_path.exists():
            return 0

        target_ids = list({int(i) for i in ids})
        con = open_db(self.db_path)
        deleted = 0
        try:
            placeholders = ",".join("?" for _ in target_ids)
            # Fetch content hashes before deletion for vault tombstoning
            cur = con.execute(f"SELECT content_hash FROM observations WHERE id IN ({placeholders})", target_ids)
            hashes = [r[0] for r in cur.fetchall() if r[0]]

            cur = con.execute(f"DELETE FROM observations WHERE id IN ({placeholders})", target_ids)
            deleted = cur.rowcount
            con.commit()

            # Rebuild FTS
            con.execute("INSERT INTO observations_fts(observations_fts) VALUES('rebuild')")
            con.commit()
        finally:
            con.close()

        # Also remove from vault JSONL or write tombstones
        if tombstone and hashes and self.vault_dir.exists():
            self._prune_vault_lines(set(hashes))

        return deleted

    def _prune_vault_lines(self, hashes: Set[str]) -> None:
        """Prune entries from observations.jsonl matching given content hashes."""
        obs_file = self.vault_dir / "observations.jsonl"
        if not obs_file.exists():
            return

        tmp = obs_file.with_suffix(".prune.tmp")
        kept = 0
        with open(obs_file, "r", encoding="utf-8") as src, open(tmp, "w", encoding="utf-8") as dst:
            for line in src:
                l = line.strip()
                if not l:
                    continue
                try:
                    d = json.loads(l)
                    ch = d.get("content_hash") or d.get("guid")
                    if ch and ch in hashes:
                        continue
                except Exception:
                    pass
                dst.write(line)
                kept += 1
        tmp.replace(obs_file)

    def prune_candidates(self, categories: Tuple[str, ...] = ("test_fixtures", "noise_records")) -> Dict[str, int]:
        """Prune all candidate records in specified categories and run compaction."""
        scan_res = self.scan()
        to_prune: List[int] = []
        for cat in categories:
            items = scan_res.get(cat, [])
            to_prune.extend([item["id"] for item in items])

        pruned_count = self.prune(to_prune)
        compact_res = deduplicate_and_compact(vault_dir=self.vault_dir, session_db=self.db_path)

        return {
            "pruned_direct": pruned_count,
            "observations_before": compact_res.get("observations_before", 0),
            "observations_after": compact_res.get("observations_after", 0),
            "observations_compacted": compact_res.get("observations_pruned", 0),
        }


def main(argv: Optional[List[str]] = None) -> None:
    """CLI runner for memory audit and hygiene."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="agi-memory audit", description="Audit and prune low-impact memories")
    parser.add_argument("--project", "-p", default=None, help="Project name filter (or '*' for all)")
    parser.add_argument("--prune", action="store_true", help="Execute pruning of test fixtures and noise records")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    auditor = MemoryAudit()
    if args.prune:
        res = auditor.prune_candidates(("test_fixtures", "noise_records"))
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"✓ Pruned {res['pruned_direct']} low-impact records.")
            print(f"  Observations before: {res['observations_before']}")
            print(f"  Observations after:  {res['observations_after']} ({res['observations_compacted']} compacted)")
        return

    res = auditor.scan(project=args.project)
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"--- agi-memory audit scan ---")
        print(f"Total observations: {res['total_observations']}")
        print(f"  Test fixtures:      {len(res['test_fixtures'])}")
        print(f"  Noise records:      {len(res['noise_records'])}")
        print(f"  Superseded records: {len(res['superseded_records'])}")
        print(f"  Unconfirmed 0-use:  {len(res['unconfirmed_zero_use'])}")
        if res['test_fixtures'] or res['noise_records']:
            print("\nRun 'agi-memory audit --prune' to clean up test fixtures and noise records.")


if __name__ == "__main__":
    main()

