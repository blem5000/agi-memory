"""Hook parity: doctor must report what is wired, not what is claimed."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agi_memory import hooks  # noqa: E402


class ParityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.patcher = mock.patch.object(Path, "home", return_value=self.home)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_nothing_installed_reads_as_nothing(self):
        rep = hooks.hook_parity("user")
        self.assertEqual([], rep["claude-code"]["installed"])
        self.assertEqual([], rep["opencode"]["installed"])
        self.assertEqual([], rep["antigravity"]["installed"])

    def test_claude_events_are_read_from_settings(self):
        settings = self.home / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"hooks": {
            "SessionStart": [{"hooks": [{"type": "command",
                                         "command": '"/usr/bin/python3" "/x/hooks.py" session-start'}]}],
            "PostToolUse": [{"hooks": [{"type": "command",
                                        "command": '"/usr/bin/python3" "/x/hooks.py" post-tool'}]}],
            # Someone else's hook must not be counted as ours.
            "Stop": [{"hooks": [{"type": "command", "command": "rm -rf /"}]}],
        }}), encoding="utf-8")
        self.assertEqual(["PostToolUse", "SessionStart"],
                         hooks.hook_parity("user")["claude-code"]["installed"])

    def test_antigravity_enabled_flag_is_not_an_event(self):
        agy = self.home / ".gemini" / "config" / "hooks.json"
        agy.parent.mkdir(parents=True)
        agy.write_text(json.dumps({"agi-memory": {"enabled": True, "Stop": [{"command": "x"}]}}),
                       encoding="utf-8")
        self.assertEqual(["Stop"], hooks.hook_parity("user")["antigravity"]["installed"])

    def test_legacy_opencode_plugin_reports_stale(self):
        # The function shape the published docs describe is exactly what the
        # installed loader rejects, so it must read as stale rather than as
        # coverage.
        plugin = hooks.opencode_plugin_path("user")
        plugin.parent.mkdir(parents=True, exist_ok=True)
        plugin.write_text(
            "export const AgiMemoryPlugin = async () => ({ event: async () => {} });\n"
            "export default AgiMemoryPlugin;",
            encoding="utf-8")
        self.assertIn("STALE", hooks.hook_parity("user")["opencode"]["installed"][0])

    def test_module_object_without_hooks_is_stale(self):
        plugin = hooks.opencode_plugin_path("user")
        plugin.parent.mkdir(parents=True, exist_ok=True)
        plugin.write_text("export default { id: 'agi-memory', async setup(ctx) {} }",
                          encoding="utf-8")
        installed = hooks.hook_parity("user")["opencode"]["installed"]
        self.assertIn("STALE", installed[0])

    def test_current_opencode_plugin_reports_its_events(self):
        plugin = hooks.opencode_plugin_path("user")
        plugin.parent.mkdir(parents=True, exist_ok=True)
        plugin.write_text(hooks.OPENCODE_PLUGIN_TEMPLATE
                          .replace("@@PY@@", "/usr/bin/python3")
                          .replace("@@HOOKS_PY@@", "/x/hooks.py"), encoding="utf-8")
        self.assertEqual(list(hooks.HOOK_SURFACES["opencode"]["events"]),
                         hooks.hook_parity("user")["opencode"]["installed"])

    def test_corrupt_config_degrades_to_empty(self):
        (self.home / ".claude").mkdir(parents=True)
        (self.home / ".claude" / "settings.json").write_text("{not json", encoding="utf-8")
        self.assertEqual([], hooks.hook_parity("user")["claude-code"]["installed"])

    def test_capabilities_are_declared_for_every_hook_installer(self):
        # A harness we install hooks for but do not describe here would be
        # invisible in doctor, which is the bug this table exists to prevent.
        src = (Path(hooks.__file__).read_text(encoding="utf-8"))
        for installer in ("install_claude_hooks", "install_agy_hooks", "install_opencode_plugin"):
            self.assertIn(installer, src)
        self.assertEqual({"claude-code", "antigravity", "opencode"}, set(hooks.HOOK_SURFACES))


class DoctorReportTests(unittest.TestCase):
    def test_doctor_includes_hooks_in_json(self):
        import argparse
        import contextlib
        import io
        from agi_memory import integrate
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            integrate.cmd_doctor(argparse.Namespace(scope="user", json=True))
        report = json.loads(buf.getvalue())
        self.assertIn("hooks", report)
        self.assertIn("claude-code", report["hooks"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
