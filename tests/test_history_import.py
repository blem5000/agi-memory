"""Native session-history import: readers, idempotence, deja-absent fallback."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agi_memory import history_import as hi  # noqa: E402


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_codex_skips_harness_preamble(self):
        f = self.root / "2026" / "09" / "06" / "rollout-2026-09-06T19-23-23-abc12345.jsonl"
        _write_jsonl(f, [
            {"timestamp": "2026-09-06T13:53:23.981Z", "type": "session_meta",
             "payload": {"session_id": "abc12345-full", "cwd": "/Users/x/Projects/agi-memory"}},
            # Harness-injected turn: must not become the session goal.
            {"timestamp": "2026-09-06T13:53:24.000Z", "type": "response_item",
             "payload": {"type": "message", "role": "user",
                         "content": [{"type": "input_text", "text": "<recommended_plugins>Airtable</recommended_plugins>"}]}},
            {"timestamp": "2026-09-06T13:53:30.000Z", "type": "response_item",
             "payload": {"type": "message", "role": "user",
                         "content": [{"type": "input_text", "text": "fix the flaky import test"}]}},
        ])
        rows = hi.codex_sessions(self.root, limit=5)
        self.assertEqual(1, len(rows))
        self.assertEqual("agi-memory", rows[0]["project"])
        self.assertEqual("fix the flaky import test", rows[0]["goal"])
        self.assertEqual("abc12345-full", rows[0]["id"])

    def test_claude_prefers_ai_title_and_reads_cwd(self):
        f = self.root / "-Users-x-Projects-app" / "sess-1.jsonl"
        _write_jsonl(f, [
            {"type": "ai-title", "aiTitle": "Micro interactions review",
             "sessionId": "sess-1", "timestamp": "2026-09-26T17:14:09.236Z",
             "cwd": "/Users/x/Projects/app"},
            {"type": "user", "sessionId": "sess-1", "timestamp": "2026-09-26T17:14:10Z",
             "cwd": "/Users/x/Projects/app",
             "message": {"role": "user", "content": "is this production quality"}},
        ])
        rows = hi.claude_sessions(self.root, limit=5)
        self.assertEqual(1, len(rows))
        self.assertEqual("Micro interactions review", rows[0]["goal"])
        self.assertEqual("app", rows[0]["project"])

    def test_opencode_reads_titles_and_summary_files(self):
        db = self.root / "opencode.db"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE session (id text, directory text, title text, "
                    "summary_files text, time_created integer, time_updated integer)")
        con.execute("INSERT INTO session VALUES (?,?,?,?,?,?)",
                    ("ses_1", "/Users/x/Projects/flutter_app", "Atomic commit",
                     json.dumps(["a.dart", "b.dart"]), 1788702803000, 1788702804000))
        con.commit()
        con.close()
        rows = hi.opencode_sessions(str(db), limit=5)
        self.assertEqual(1, len(rows))
        self.assertEqual("flutter_app", rows[0]["project"])
        self.assertEqual(["a.dart", "b.dart"], rows[0]["touched"])
        # Millis must land as an ISO timestamp, not year 56000.
        self.assertTrue(rows[0]["started"].startswith("2026-"), rows[0]["started"])

    def test_missing_home_dirs_are_empty_not_errors(self):
        empty = self.root / "nothing-here"
        self.assertEqual([], hi.codex_sessions(empty, limit=5))
        self.assertEqual([], hi.claude_sessions(empty, limit=5))
        self.assertEqual([], hi.opencode_sessions(str(empty / "opencode.db"), limit=5))

    def test_corrupt_jsonl_lines_are_skipped(self):
        f = self.root / "s" / "rollout-x.jsonl"
        f.parent.mkdir(parents=True)
        f.write_text('{"type":"session_meta","payload":{"session_id":"s1","cwd":"/p/q"}}\n'
                     "not json at all\n{broken\n", encoding="utf-8")
        self.assertEqual(1, len(hi.codex_sessions(self.root, limit=5)))


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "memory.db"
        self.addCleanup(self.tmp.cleanup)

    def _sessions(self):
        return [{"id": "abc12345-full", "project": "agi-memory", "harness": "codex",
                 "goal": "fix the import test", "started": "2026-09-06T13:53:23",
                 "ended": "2026-09-06T13:55:00", "touched": ["src/x.py"],
                 "prompts": ["fix the import test", "now add a case for the fallback"]}]

    def test_import_sessions_records_l1_once(self):
        orig = hi.list_sessions
        hi.list_sessions = lambda *a, **k: self._sessions()
        self.addCleanup(setattr, hi, "list_sessions", orig)
        first = hi.import_sessions(db_path=self.db)
        self.assertEqual(1, first["imported"])
        second = hi.import_sessions(db_path=self.db)
        self.assertEqual(0, second["imported"], "re-running must not duplicate")
        from agi_memory.layers.session_layer import SessionLayer
        titles = [o["title"] for o in SessionLayer(db_path=self.db).list_observations(limit=50)]
        self.assertTrue(any("[codex:abc12345]" in t for t in titles), titles)

    def test_import_index_is_idempotent(self):
        orig = hi.list_sessions
        hi.list_sessions = lambda *a, **k: self._sessions()
        self.addCleanup(setattr, hi, "list_sessions", orig)
        self.assertEqual(1, hi.import_index(db_path=self.db)["indexed"])
        self.assertEqual(0, hi.import_index(db_path=self.db)["indexed"])

    def test_dry_run_writes_nothing(self):
        orig = hi.list_sessions
        hi.list_sessions = lambda *a, **k: self._sessions()
        self.addCleanup(setattr, hi, "list_sessions", orig)
        self.assertEqual(1, hi.import_sessions(db_path=self.db, dry_run=True)["imported"])
        from agi_memory.layers.session_layer import SessionLayer
        self.assertEqual(0, SessionLayer(db_path=self.db).count_observations())

    def test_project_filter_excludes_other_repos(self):
        rows = self._sessions() + [dict(self._sessions()[0], id="other1", project="unrelated")]
        orig = hi.list_sessions
        hi.list_sessions = lambda *a, **k: rows
        self.addCleanup(setattr, hi, "list_sessions", orig)
        res = hi.import_sessions(project="agi-memory", db_path=self.db)
        self.assertEqual(1, res["listed"])


class OriginTests(unittest.TestCase):
    def test_imported_history_keeps_its_origin(self):
        # The MCP schema advertises these; normalize_origin() silently rewrites
        # anything it does not know, so a gap between the two lists turns an
        # unverified import into "the agent decided this".
        from agi_memory.layers.session_layer import ORIGINS, normalize_origin
        from agi_memory.mcp_server import TOOLS
        schema = next(t for t in TOOLS if t["name"] == "memory_record")
        advertised = schema["inputSchema"]["properties"]["origin"]["enum"]
        self.assertTrue(set(advertised) <= set(ORIGINS),
                        f"advertised but rejected: {set(advertised) - set(ORIGINS)}")
        for origin in advertised:
            self.assertEqual(origin, normalize_origin(origin), origin)

    def test_history_import_origin_is_not_downgraded(self):
        from agi_memory.layers.session_layer import normalize_origin
        self.assertEqual("history-import", normalize_origin("history-import"))
        self.assertEqual("agent-inferred", normalize_origin("something-made-up"))


class BootstrapTests(unittest.TestCase):
    def test_bootstrap_imports_native_history(self):
        from agi_memory import bootstrap, history_import

        def fake(**kwargs):
            self.assertEqual(3, kwargs["limit"])
            return {"listed": 2, "imported": 2, "skipped": 0, "ids": [1, 2]}

        # Restored via addCleanup, not a bare finally: a leak here replaces the
        # real import_sessions for every later test in the run.
        orig = history_import.import_sessions
        history_import.import_sessions = fake
        self.addCleanup(setattr, history_import, "import_sessions", orig)

        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            bootstrap.main(["--repo", ".", "--max-commits", "0",
                            "--with-history", "--history-limit", "3", "--json"])
        res = json.loads(buf.getvalue())
        self.assertEqual(2, res.get("history_imported"))

    def test_legacy_with_deja_flag_still_works(self):
        from agi_memory import bootstrap, history_import
        orig = history_import.import_sessions
        history_import.import_sessions = lambda **k: {"listed": 1, "imported": 1,
                                                      "skipped": 0, "ids": [1]}
        self.addCleanup(setattr, history_import, "import_sessions", orig)
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            bootstrap.main(["--repo", ".", "--max-commits", "0", "--with-deja", "--json"])
        self.assertEqual(1, json.loads(buf.getvalue()).get("history_imported"))



if __name__ == "__main__":
    unittest.main(verbosity=2)
