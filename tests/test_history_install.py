"""Install-time history import: discovery must be honest, consent must be real.

The promise this feature makes is "a new user's existing history is there before
their first prompt". Two ways that fails, both covered here:

- claiming coverage it does not have -- a tool is detected, has no reader, and
  is quietly absent from the report, which reads as "we covered everything";
- importing without asking, because the caller happened to be non-interactive.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agi_memory import history_import as hi  # noqa: E402


class ScanTests(unittest.TestCase):
    def test_undetected_tools_are_not_reported(self):
        rows = hi.scan({"claude": True, "cursor": False, "codex": True})
        self.assertEqual({"claude", "codex"}, {r["tool"] for r in rows})

    def test_every_detected_tool_appears_with_a_reason_when_skipped(self):
        rows = hi.scan({t: True for t in ("claude", "cursor", "hermes", "agy")})
        by = {r["tool"]: r for r in rows}
        # The readable one is not blocked...
        self.assertEqual("claude", by["claude"]["reader"])
        # ...and a tool with no reader says so rather than vanishing.
        self.assertIsNone(by["cursor"]["reader"])
        self.assertIn("no reader", by["cursor"]["reason"])
        # ...and the two we refuse on purpose say why, in specific terms.
        self.assertIn("auth headers", by["hermes"]["reason"])
        self.assertIn("protobuf", by["agy"]["reason"])

    def test_blocked_tools_never_get_a_reader(self):
        for tool in hi.BLOCKED:
            self.assertNotIn(tool, hi.TOOL_READERS,
                             f"{tool} is blocked but also readable -- pick one")

    def test_every_reader_is_reachable(self):
        for tool, reader in hi.TOOL_READERS.items():
            self.assertIn(reader, hi.READERS, tool)

    def test_scan_counts_sessions_without_raising(self):
        rows = hi.scan({"codex": True})
        self.assertEqual(1, len(rows))
        self.assertIsInstance(rows[0]["sessions"], int)


class ImportAllTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "m.db"
        self.addCleanup(self.tmp.cleanup)

    def test_import_all_is_idempotent(self):
        first = hi.import_all(limit=5, db_path=self.db)
        second = hi.import_all(limit=5, db_path=self.db)
        self.assertGreater(first["imported"], 0, first)
        self.assertEqual(0, second["imported"],
                         "a second install must not duplicate memories")

    def test_totals_match_the_per_tool_rows(self):
        res = hi.import_all(limit=3, db_path=self.db)
        self.assertEqual(sum(r.get("indexed", 0) for r in res["per_tool"].values()),
                         res["indexed"])
        self.assertEqual(sum(r.get("imported", 0) for r in res["per_tool"].values()),
                         res["imported"])


class _FakeTool:
    """Mock(name=...) sets the mock's repr name, not the attribute, so the
    integration has to be a real object for `t.name` to mean anything."""

    def __init__(self, name, detected=True):
        self.name = name
        self._detected = detected

    def is_detected(self):
        return self._detected


class ConsentTests(unittest.TestCase):
    """The import runs only on an explicit yes."""

    def _tools(self):
        return [_FakeTool("claude")]

    def test_declining_imports_nothing(self):
        from agi_memory import integrate
        calls = []
        with mock.patch.object(hi, "import_all",
                               side_effect=lambda **k: calls.append(k) or {"per_tool": {}, "indexed": 0, "imported": 0}), \
             mock.patch.object(integrate, "INTEGRATIONS", self._tools()), \
             mock.patch.object(sys.stdin, "isatty", return_value=True), \
             mock.patch("builtins.input", return_value="n"):
            res = integrate.offer_history_import()
        self.assertIsNone(res)
        self.assertEqual([], calls, "declining must not read a single transcript")

    def test_typing_yes_imports(self):
        from agi_memory import integrate
        calls = []
        with mock.patch.object(hi, "import_all",
                               side_effect=lambda **k: calls.append(k) or {"per_tool": {}, "indexed": 1, "imported": 1}), \
             mock.patch.object(integrate, "INTEGRATIONS", self._tools()), \
             mock.patch.object(sys.stdin, "isatty", return_value=True), \
             mock.patch("builtins.input", return_value="y"):
            res = integrate.offer_history_import()
        self.assertIsNotNone(res)
        self.assertEqual(1, len(calls))

    def test_non_interactive_imports_nothing(self):
        from agi_memory import integrate
        calls = []
        with mock.patch.object(hi, "import_all",
                               side_effect=lambda **k: calls.append(k) or {"per_tool": {}, "indexed": 0, "imported": 0}), \
             mock.patch.object(integrate, "INTEGRATIONS", self._tools()), \
             mock.patch.object(sys.stdin, "isatty", return_value=False):
            res = integrate.offer_history_import(non_interactive=True)
        self.assertIsNone(res)
        self.assertEqual([], calls, "a piped install must not read transcripts unasked")

    def test_no_history_flag_short_circuits(self):
        from agi_memory import integrate
        calls = []
        with mock.patch.object(hi, "import_all", side_effect=lambda **k: calls.append(k) or {}):
            self.assertIsNone(integrate.offer_history_import(assume_no=True))
        self.assertEqual([], calls)

    def test_yes_flag_imports_without_asking(self):
        from agi_memory import integrate
        called = {}

        def fake(**kwargs):
            called.update(kwargs)
            return {"per_tool": {"claude": {"indexed": 3, "imported": 2}},
                    "indexed": 3, "imported": 2}

        with mock.patch.object(hi, "import_all", fake), \
             mock.patch.object(integrate, "INTEGRATIONS", self._tools()), \
             mock.patch.object(sys.stdin, "isatty", return_value=False):
            res = integrate.offer_history_import(non_interactive=True, assume_yes=True,
                                                 limit=2)
        self.assertIsNotNone(res)
        self.assertEqual(2, res["imported"])
        self.assertEqual(2, called.get("limit"), "the digest cap must reach the importer")

    def test_install_wires_the_offer_in(self):
        from agi_memory import integrate
        src = Path(integrate.__file__).read_text(encoding="utf-8")
        self.assertIn("offer_history_import(", src)
        self.assertIn('"--no-history"', src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
