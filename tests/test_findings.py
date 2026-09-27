"""Findings: evidence attached to recalled memories, never verdicts.

The design decision these tests protect: there is no contradiction detector and
no age-based invalidation. Deciding that two memories disagree is a judgement,
and a rule that makes it will be wrong invisibly. So a finding states what was
observed and leaves the conclusion to the agent reading it -- which is only
worth anything if the findings never dress themselves up as verdicts.
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agi_memory import findings  # noqa: E402
from agi_memory.layers.code_layer import CodeLayer  # noqa: E402
from agi_memory.layers.session_layer import SessionLayer  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "m.db"
        self.addCleanup(self.tmp.cleanup)
        self.l = SessionLayer(project="demo", db_path=self.db)

    def _record(self, text, title, files=None, origin="agent-inferred", days_ago=0):
        rec = self.l.record(text=text, title=title, project="demo", origin=origin)
        con = sqlite3.connect(self.db)
        con.execute("UPDATE observations SET files_modified = ?, created_at_epoch = ? WHERE id = ?",
                    (json.dumps(files or []),
                     int((time.time() - days_ago * 86400) * 1000), rec["id"]))
        con.commit()
        con.close()
        return str(rec["id"])

    def _shown(self, oid, n=5):
        """Put read receipts on a row the way recall does.

        Goes through mark_shown rather than writing the table directly: it is
        the real writer, and it is what creates the table on a fresh store.
        """
        for _ in range(n):
            self.l.mark_shown([oid])


class DriftFindingTests(_Base):
    def _index(self, name, body="def f():\n    return 1\n"):
        """Index a file the way the CLI does: a path relative to root_dir, with
        the indexer run from that root."""
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            Path(name).write_text(body, encoding="utf-8")
            CodeLayer(project="demo", db_path=self.db).index_file(
                name, project="demo", root_dir=self.root)
        finally:
            os.chdir(cwd)
        return self.root / name

    def test_memory_pointing_at_a_deleted_file_is_flagged(self):
        src = self._index("gone.py")
        oid = self._record("Always call f() before deploying.", "Deploy rule",
                           files=["gone.py"])
        self.assertEqual([], findings.for_observations([oid], project="demo", db_path=self.db),
                         "nothing is missing yet")
        src.unlink()
        out = findings.for_observations([oid], project="demo", db_path=self.db)
        self.assertTrue(out, "a claim pointing at a deleted file must be flagged")
        self.assertIn("gone.py", out[0])
        self.assertIn("no longer exist", out[0])

    def test_surviving_file_produces_nothing(self):
        self._index("here.py", "x = 1\n")
        oid = self._record("x is defined in here.py.", "X rule", files=["here.py"])
        self.assertEqual([], findings.for_observations([oid], project="demo", db_path=self.db))

    def test_unindexed_reference_is_unknown_not_gone(self):
        # Never indexed: the index cannot say the file is gone, and calling it
        # gone would be a claim it cannot support.
        oid = self._record("Uses lib/thing.py somewhere.", "Thing rule",
                           files=["lib/thing.py"])
        self.assertEqual([], findings.for_observations([oid], project="demo", db_path=self.db))


class ProvenanceFindingsTests(_Base):
    def test_served_inference_never_confirmed_is_flagged(self):
        oid = self._record("The cache key includes the tenant id.", "Cache key rule",
                           origin="agent-inferred")
        self._shown(oid, 4)
        out = findings.for_observations([oid], project="demo", db_path=self.db)
        self.assertTrue(any("inference" in f and "never confirmed" in f for f in out), out)

    def test_confirmed_inference_is_not_flagged(self):
        oid = self._record("The cache key includes the tenant id.", "Cache key rule",
                           origin="agent-inferred")
        self._shown(oid, 4)
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO observations (project, type, title, facts, narrative, "
                    "concepts, files_read, files_modified, prompt_number, "
                    "discovery_tokens, created_at, created_at_epoch, content_hash, "
                    "generated_by_model, relevance_count, sync_rev, supersedes_refs) "
                    "VALUES ('demo','decision','later','[]','confirms it','[]','[]','[]',"
                    "1,0,'2026-01-01',0,'h2','test',0,'1', ?)",
                    (json.dumps([oid]),))
        con.commit()
        con.close()
        out = findings.for_observations([oid], project="demo", db_path=self.db)
        self.assertFalse(any("never confirmed" in f for f in out), out)

    def test_old_and_hot_is_a_prompt_not_an_invalidation(self):
        oid = self._record("Port 8080 is required behind the proxy.", "Port rule",
                           origin="user-confirmed", days_ago=400)
        self._shown(oid, 6)
        out = findings.for_observations([oid], project="demo", db_path=self.db)
        self.assertTrue(any("worth re-checking" in f for f in out), out)

    def test_quiet_old_memory_is_left_alone(self):
        oid = self._record("Nobody reads this.", "Quiet rule", days_ago=400)
        self.assertEqual([], findings.for_observations([oid], project="demo", db_path=self.db))


class NeutralityTests(_Base):
    """A finding that reads as a verdict is the thing this module must not do."""

    BANNED = ("contradict", "conflict", "is wrong", "invalid", "obsolete",
              "outdated", "stale")

    def test_no_finding_claims_a_verdict(self):
        oid = self._record("The rule is X.", "Rule", origin="agent-inferred",
                           days_ago=900)
        self._shown(oid, 9)
        for line in findings.for_observations([oid], project="demo", db_path=self.db):
            low = line.lower()
            for word in self.BANNED:
                self.assertNotIn(word, low, f"verdict language in: {line}")

    def test_render_says_what_the_findings_are(self):
        block = findings.render(["#1 something"])
        self.assertIn("evidence, not verdicts", block)
        self.assertIn("#1 something", block)

    def test_render_is_empty_when_there_is_nothing(self):
        self.assertEqual("", findings.render([]))
        self.assertEqual("", findings.render(None))

    def test_findings_are_bounded(self):
        ids = [self._record(f"Rule number {n}.", f"Rule {n}", origin="agent-inferred")
               for n in range(8)]
        for oid in ids:
            self._shown(oid, 5)
        self.assertLessEqual(len(findings.for_observations(ids, project="demo", db_path=self.db)),
                             findings.MAX_FINDINGS)

    def test_unknown_ids_do_not_raise(self):
        self.assertEqual([], findings.for_observations([], project="demo", db_path=self.db))
        self.assertEqual([], findings.for_observations(["999999"], project="demo", db_path=self.db))


class WiringTests(_Base):
    def test_recall_appends_the_block(self):
        oid = self._record("Port 8080 is required behind the proxy.", "Port rule",
                           origin="user-confirmed", days_ago=400)
        self._shown(oid, 6)
        from agi_memory import mcp_server
        with mock.patch.object(mcp_server, "SessionLayer",
                               lambda **kw: SessionLayer(db_path=self.db, **kw)):
            out = mcp_server.call_tool("memory_recall",
                                       {"query": "port 8080 proxy", "project": "demo"})
        self.assertIn("## findings", out)

    def test_recall_is_unchanged_when_there_is_nothing_to_say(self):
        oid = self._record("A quiet memory about widgets.", "Widget rule")
        from agi_memory import mcp_server
        with mock.patch.object(mcp_server, "SessionLayer",
                               lambda **kw: SessionLayer(db_path=self.db, **kw)):
            out = mcp_server.call_tool("memory_recall",
                                       {"query": "widgets", "project": "demo"})
        self.assertNotIn("## findings", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
