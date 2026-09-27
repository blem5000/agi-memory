"""One server id in two scopes of one assistant is a broken configuration.

Reported from a Claude Code session as "[Conflicting scopes] ... OAuth tokens are
stored per endpoint". The local entry it named pointed at a project `.venv` that
had since been deleted, so it was not merely ambiguous: if that scope had won,
the server could not have started at all, while still looking configured.

These tests build the shape in a temp HOME and assert it is detected, so the
next time an install leaves a stale registration behind it is reported by the
installer rather than by a session-start warning the user cannot act on.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agi_memory import integrate  # noqa: E402

GOOD_PY = sys.executable  # exists


class _FakeTool:
    def __init__(self, name, user_path, project_path):
        self.name = name
        self._user = Path(user_path)
        self._project = Path(project_path)

    def get_config_path(self, scope="user"):
        return self._user if scope == "user" else self._project


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class ScopeConflictTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.user_cfg = self.root / "home" / ".claude.json"
        self.proj_cfg = self.root / "proj" / ".claude.json"
        self.cwd = self.root / "proj"
        self.cwd.mkdir(parents=True, exist_ok=True)
        self.addCleanup(self.tmp.cleanup)

    def _tool(self, name="claude"):
        return _FakeTool(name, self.user_cfg, self.proj_cfg)

    def _detect(self, tool=None, extra_tools=()):
        tools = [tool or self._tool(), *extra_tools]
        with mock.patch.object(integrate, "INTEGRATIONS", tools), \
             mock.patch("pathlib.Path.cwd", return_value=self.cwd):
            return integrate.find_conflicting_scopes("agi-memory")

    def test_single_registration_is_not_a_clash(self):
        _write(self.user_cfg, {"mcpServers": {"agi-memory": {"command": GOOD_PY}}})
        rows = self._detect()
        self.assertEqual(1, len(rows))
        self.assertTrue(rows[0]["exists"])

    def test_same_id_in_two_scopes_is_a_clash(self):
        _write(self.user_cfg, {
            "mcpServers": {"agi-memory": {"command": GOOD_PY}},
            "projects": {"/some/where": {"mcpServers": {
                "agi-memory": {"command": "/opt/homebrew/bin/python3"}}}},
        })
        self.assertEqual(2, len(self._detect()))

    def test_deleted_interpreter_is_reported_as_cannot_start(self):
        # The exact case reported: a project .venv that no longer exists.
        dead = self.root / "gone" / ".venv" / "bin" / "python"
        _write(self.user_cfg, {
            "mcpServers": {"agi-memory": {"command": GOOD_PY}},
            "projects": {"/some/where": {"mcpServers": {"agi-memory": {"command": str(dead)}}}},
        })
        rows = self._detect()
        dead_rows = [r for r in rows if not r["exists"]]
        self.assertEqual(1, len(dead_rows), rows)
        self.assertIn("gone", dead_rows[0]["command"])

    def test_one_registration_per_assistant_is_not_a_clash(self):
        # The same id in several assistants' configs is the intended state, not
        # a conflict. Reporting it would cry wolf on every install.
        a = _FakeTool("cursor", self.root / "cursor.json", self.root / "c2.json")
        b = _FakeTool("codexish", self.root / "other.json", self.root / "o2.json")
        for p in (a._user, b._user):
            _write(p, {"mcpServers": {"agi-memory": {"command": GOOD_PY}}})
        rows = self._detect(tool=a, extra_tools=(b,))
        self.assertEqual(2, len(rows))
        by_tool = {}
        for r in rows:
            by_tool.setdefault(r["tool"], []).append(r)
        self.assertTrue(all(len(v) == 1 for v in by_tool.values()), by_tool)

    def test_mcp_json_counts_as_a_claude_scope(self):
        # Claude Code reads .mcp.json too, so the same id there is a clash.
        _write(self.user_cfg, {"mcpServers": {"agi-memory": {"command": GOOD_PY}}})
        _write(self.cwd / ".mcp.json",
               {"mcpServers": {"agi-memory": {"command": GOOD_PY}}})
        self.assertEqual(2, len(self._detect()))

    def test_detection_never_edits_the_config(self):
        before = {"mcpServers": {"agi-memory": {"command": GOOD_PY}},
                  "projects": {"/x": {"mcpServers": {"agi-memory": {"command": "/nope/python"}}}}}
        _write(self.user_cfg, before)
        raw = self.user_cfg.read_text()
        self._detect()
        self.assertEqual(raw, self.user_cfg.read_text(),
                         "a read-only reporter must not rewrite anyone's config")

    def test_corrupt_config_does_not_raise(self):
        self.user_cfg.parent.mkdir(parents=True, exist_ok=True)
        self.user_cfg.write_text("{not json", encoding="utf-8")
        self.assertEqual([], self._detect())


if __name__ == "__main__":
    unittest.main(verbosity=2)
