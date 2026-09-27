"""Retrieval quality: exact-title, recency, and writer visibility.

All three came from measuring a real 15k-record store rather than from the
spec, and all three failed in the same way -- recall returned something
topically adjacent and said nothing about who wrote it.

  - asking for a title that had four exact versions returned an unrelated
    memory from a different project that merely shared the words;
  - nothing in the ranking preferred a newer answer over an older one, so a fact
    that changed over months could resolve to the stale version;
  - the retrieval line carried no writer, so a reader could not tell its own
    conclusion from a sibling process's inference.
"""
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agi_memory.layers.session_layer import SessionLayer  # noqa: E402


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "m.db"
        self.addCleanup(self.tmp.cleanup)
        self.l = SessionLayer(project="demo", db_path=self.db)

    def _record(self, text, title, days_ago=0, agent=""):
        # created_at_epoch is milliseconds everywhere in this codebase; writing
        # seconds here is exactly the mistake the recency test guards against.
        when = int((time.time() - days_ago * 86400) * 1000)
        rec = self.l.record(text=text, title=title, project="demo", agent=agent)
        con = sqlite3.connect(self.db)
        con.execute("UPDATE observations SET created_at_epoch = ? WHERE id = ?",
                    (when, rec["id"]))
        con.commit()
        con.close()
        return rec["id"]

    def test_exact_title_outranks_a_body_that_mentions_the_words(self):
        exact = self._record(
            "The launch configuration is the source of truth for web builds.",
            "Web flavor selection requires dart-define", days_ago=200)
        self._record(
            "Nothing committed yet; commit is the immediate next step to protect "
            "recovery from the session that closed without one.",
            "Session closed with a blocker", days_ago=0)
        hits = self.l.search("Web flavor selection requires dart-define", limit=3)
        self.assertTrue(hits)
        self.assertEqual(str(exact), hits[0].ref,
                         f"exact title lost to keyword-adjacent body: {hits[0].text[:80]}")

    def test_newer_wins_when_relevance_is_close(self):
        # Same topic, same wording, different ages: the fresh one must lead.
        old = self._record("Use flavor dev for staging builds.",
                           "Staging build uses the dev flavor", days_ago=300)
        new = self._record("Use flavor prod for staging builds.",
                           "Staging build uses the prod flavor", days_ago=1)
        hits = self.l.search("staging build uses the flavor", limit=4)
        refs = [h.ref for h in hits]
        self.assertIn(str(new), refs, refs)
        if str(old) in refs:
            self.assertLess(refs.index(str(new)), refs.index(str(old)),
                            f"stale answer outranked the current one: {refs}")

    def test_recency_never_hides_an_old_but_relevant_memory(self):
        old = self._record("The ledger is the system of record, not a feeder.",
                           "Ledger authority", days_ago=900)
        hits = self.l.search("ledger system of record feeder", limit=5)
        self.assertIn(str(old), [h.ref for h in hits],
                      "recency must be a tiebreaker, never a filter")

    def test_writer_reaches_the_retrieval_line(self):
        i = self._record("Port 8080 is required behind the proxy.",
                         "Port rule", agent="host:1234:codex")
        text = self.l.search("port 8080 proxy", limit=3)[0].text
        self.assertIn("host 1234 codex", text, text[-80:])
        self.assertIn("(via ", text)

    def test_row_without_a_writer_is_not_padded(self):
        i = self._record("No writer recorded here.", "Anonymous rule")
        text = self.l.search("no writer recorded", limit=3)[0].text
        self.assertNotIn("(via ", text)

    def test_fts_metacharacters_do_not_break_the_query(self):
        self._record("A hyphen and a quote: dart-define and \"quoted\".",
                     "Punctuation survives", days_ago=1)
        for q in ('dart-define', 'a "quoted" word', "colon: value", "dash-and_underscore"):
            hits = self.l.search(q, limit=2)   # must not raise
            self.assertIsInstance(hits, list)

    def test_superseded_still_ranks_last(self):
        live = self._record("Current answer: use port 8080.", "Port answer", days_ago=0)
        dead = self._record("Old answer: use port 9090.", "Port answer old", days_ago=0)
        con = sqlite3.connect(self.db)
        con.execute("UPDATE observations SET type='superseded', superseded_by=? WHERE id=?",
                    (live, dead))
        con.commit()
        con.close()
        hits = self.l.search("port answer", limit=5)
        refs = [h.ref for h in hits]
        if str(dead) in refs and str(live) in refs:
            self.assertLess(refs.index(str(live)), refs.index(str(dead)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
