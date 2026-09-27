"""Cross-agent provenance: two agents, one project, one store.

The bug these cover: the session-reuse key was (project, recent) alone, so two
agents working the same repo shared one episodic row -- their events interleaved
and "what was the last session doing" reported a peer's work as the caller's.
And `origin="user-confirmed", the strongest field in recall ranking, was an
argument the model chose for itself.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agi_memory import config  # noqa: E402
from agi_memory.layers.episodic_layer import EpisodicLayer  # noqa: E402
from agi_memory.layers.session_layer import SessionLayer  # noqa: E402


class ResolveAgentIdTests(unittest.TestCase):
    def test_declared_env_wins_and_is_labelled_declared(self):
        with mock.patch.dict(os.environ, {"AGI_AGENT_ID": "reviewer-7"}):
            self.assertEqual(("reviewer-7", config.DECLARED), config.resolve_agent_id())

    def test_fallback_is_a_process_and_says_so(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            agent, kind = config.resolve_agent_id("codex")
        self.assertEqual(config.PROCESS, kind)
        self.assertIn(str(os.getpid()), agent)
        self.assertIn("codex", agent)

    def test_two_processes_get_distinct_ids(self):
        # The whole point: a host:pid separates concurrent processes even though
        # it cannot name a claimant. os.getpid is patched to stand for a peer.
        with mock.patch.dict(os.environ, {}, clear=True):
            mine = config.resolve_agent_id()[0]
            with mock.patch("os.getpid", return_value=os.getpid() + 1):
                theirs = config.resolve_agent_id()[0]
        self.assertNotEqual(mine, theirs)


class AttestWriteOriginTests(unittest.TestCase):
    def test_model_cannot_assert_user_confirmed(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            origin, why = config.attest_write_origin("user-confirmed")
        self.assertEqual("agent-inferred", origin)
        self.assertIn("cannot attest", why)

    def test_human_override_is_honoured(self):
        with mock.patch.dict(os.environ, {"AGI_TRUST_WRITE": "1"}):
            self.assertEqual(("user-confirmed", ""),
                             config.attest_write_origin("user-confirmed"))

    def test_other_origins_pass_through_untouched(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            for o in ("agent-inferred", "bootstrapped", "history-import", None, ""):
                self.assertEqual(((o or "").strip().lower(), ""),
                                 config.attest_write_origin(o))


class SessionIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "m.db"
        self.addCleanup(self.tmp.cleanup)

    def test_two_agents_get_two_sessions(self):
        ep = EpisodicLayer(project="demo", db_path=self.db)
        a = ep.start_session(project="demo", agent="host:1:codex")
        b = ep.start_session(project="demo", agent="host:2:claude")
        self.assertNotEqual(a["session_id"], b["session_id"])
        # Each agent's own last session is its own, not the newest row.
        self.assertEqual("host:1:codex",
                         ep.get_last_session(project="demo", agent="host:1:codex")["agent"])
        self.assertEqual("host:2:claude",
                         ep.get_last_session(project="demo", agent="host:2:claude")["agent"])

    def test_pre_identity_rows_stay_readable(self):
        ep = EpisodicLayer(project="demo", db_path=self.db)
        ep.start_session(project="demo")  # agent='' -- every row written before this
        rows = ep.get_timeline(project="demo")
        self.assertEqual(1, len(rows))
        self.assertEqual("", rows[0]["agent"])
        self.assertEqual(1, len(ep.get_timeline(project="demo", agent="")))

    def test_migration_is_idempotent_on_an_existing_database(self):
        # A bare ALTER TABLE would raise "duplicate column name" on the second
        # open, which is every open after the first.
        for _ in range(3):
            ep = EpisodicLayer(project="demo", db_path=self.db)
            ep.start_session(project="demo", agent="host:9:x")

    def test_recap_names_the_writer(self):
        ep = EpisodicLayer(project="demo", db_path=self.db)
        s = ep.start_session(project="demo", agent="host:1:codex", goal="ship it")
        text = EpisodicLayer.format_recap(ep.get_session(s["session_id"]))
        self.assertIn("host:1:codex", text)

    def test_recap_says_unknown_when_it_cannot_tell(self):
        ep = EpisodicLayer(project="demo", db_path=self.db)
        s = ep.start_session(project="demo", goal="ship it")
        text = EpisodicLayer.format_recap(ep.get_session(s["session_id"]))
        self.assertIn("writer unknown", text)


class ObservationProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "m.db"
        self.addCleanup(self.tmp.cleanup)

    def test_record_stores_the_agent(self):
        l1 = SessionLayer(project="demo", db_path=self.db)
        rec = l1.record(text="always run the offline suite", title="Test gate",
                        project="demo", agent="host:1:codex")
        self.assertEqual("host:1:codex", rec["agent"])

    def test_promotion_carries_attribution_into_the_durable_text(self):
        from agi_memory import promote
        l1 = SessionLayer(project="demo", db_path=self.db)
        l1.record(text="the ledger is the system of record", title="Ledger rule",
                  project="demo", category="decision", origin="user-confirmed",
                  agent="host:1:codex")
        # collect() reads a module-level DB, not the one this test wrote to.
        with mock.patch.object(promote, "DB", self.db):
            rows = promote.collect(project="demo")
        promoted = [t for t, _ in rows if "ledger" in t.lower()]
        self.assertTrue(promoted, rows)
        self.assertIn("user-confirmed", promoted[0])
        self.assertIn("host:1:codex", promoted[0])

    def test_inferred_promotions_are_marked_as_such(self):
        from agi_memory import promote
        l1 = SessionLayer(project="demo", db_path=self.db)
        l1.record(text="the webhook retries five times", title="Retry cap",
                  project="demo", category="decision", origin="agent-inferred",
                  agent="host:2:claude")
        with mock.patch.object(promote, "DB", self.db):
            rows = promote.collect(project="demo")
        promoted = [t for t, _ in rows if "webhook" in t.lower()]
        self.assertTrue(promoted, rows)
        self.assertIn("agent-inferred", promoted[0])


class ReusePolicyTests(unittest.TestCase):
    """Reuse stays the default; only a session still taking writes forces a new one.

    The 12-hour window this replaced could not tell "the last CLI call already
    finished" from "another agent is working right now", so it merged both. The
    discriminator is the session's last recorded event, not the pid: os.kill
    cannot probe liveness portably -- on Windows os.kill(pid, 0) terminates the
    process, which is how the Windows CI run caught it.
    """
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "m.db"
        self.addCleanup(self.tmp.cleanup)
        from agi_memory import mcp_server
        mcp_server._SESSION_REGISTERED.clear()
        self.addCleanup(mcp_server._SESSION_REGISTERED.clear)

    def _ensure(self, agent_id):
        from agi_memory import mcp_server
        mcp_server._SESSION_REGISTERED.clear()
        with mock.patch.dict(os.environ, {"AGI_AGENT_ID": agent_id}, clear=True), \
             mock.patch.object(mcp_server, "EpisodicLayer",
                               lambda **kw: EpisodicLayer(db_path=self.db, **kw)):
            return mcp_server._ensure_session("demo")

    def _event(self, session_id, seconds_ago=0):
        # Written through SQLite's own clock, because that is what log_event
        # does and what _wrote_recently compares against.
        ep = EpisodicLayer(db_path=self.db)
        con = ep._get_con()
        con.execute("INSERT INTO episodic_events (session_id, project, event_type, "
                    "summary, details, timestamp) VALUES (?,?,?,?,?, "
                    "datetime('now', ?))",
                    (session_id, "demo", "command", "pytest", "{}",
                     f"-{int(seconds_ago)} seconds"))
        con.commit()
        con.close()

    def test_quiet_writer_is_adopted_not_duplicated(self):
        self._ensure("host:1:codex")
        ep = EpisodicLayer(db_path=self.db)
        first = ep.get_last_session(project="demo")
        # Its last event was an hour ago: the writer is gone.
        self._event(first["session_id"], seconds_ago=3600)
        self._ensure("host:2:codex")
        second = ep.get_last_session(project="demo")
        self.assertEqual(first["session_id"], second["session_id"],
                         "a finished writer must not spawn a new session")
        self.assertEqual("host:2:codex", second["agent"], "adoption should stamp the writer")

    def test_active_writer_forces_a_separate_session(self):
        self._ensure("host:1:codex")
        ep = EpisodicLayer(db_path=self.db)
        first = ep.get_last_session(project="demo")
        self._event(first["session_id"])   # just now: a peer is mid-flight
        self._ensure("host:2:claude")
        rows = ep.get_timeline(project="demo")
        self.assertEqual(2, len(rows), "a live peer must not be merged into")
        self.assertIn("host:2:claude", [r["agent"] for r in rows])

    def test_first_call_of_a_fresh_project_always_starts_one(self):
        self._ensure("host:3:codex")
        self.assertEqual(1, len(EpisodicLayer(db_path=self.db).get_timeline(project="demo")))


class McpPathTests(unittest.TestCase):
    def test_mcp_record_cannot_mint_the_top_trust_tier(self):
        from agi_memory import mcp_server
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "m.db"
            with mock.patch.dict(os.environ, {}, clear=True), \
                 mock.patch.object(mcp_server, "SessionLayer",
                                   lambda **kw: SessionLayer(db_path=db, **kw)):
                out = mcp_server.call_tool("memory_record", {
                    "text": "the user prefers tabs over spaces",
                    "title": "Indentation",
                    "project": "demo",
                    "origin": "user-confirmed",
                })
            self.assertIn("downgraded", out)
            rows = SessionLayer(db_path=db).list_observations(limit=5)
            self.assertEqual("agent-inferred", rows[0].get("origin"))

    def test_mcp_record_still_honours_the_override(self):
        from agi_memory import mcp_server
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "m.db"
            with mock.patch.dict(os.environ, {"AGI_TRUST_WRITE": "1"}), \
                 mock.patch.object(mcp_server, "SessionLayer",
                                   lambda **kw: SessionLayer(db_path=db, **kw)):
                mcp_server.call_tool("memory_record", {
                    "text": "the user prefers tabs", "title": "Indentation",
                    "project": "demo", "origin": "user-confirmed"})
            rows = SessionLayer(db_path=db).list_observations(limit=5)
            self.assertEqual("user-confirmed", rows[0].get("origin"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
