"""The generated OpenCode plugin must satisfy the loader that actually runs.

This file exists because the shape was verified against the published docs and
the @opencode-ai/plugin types, and both describe a bare plugin function. The
installed opencode 2.0.18 rejects that with:

    Plugin must export a default definition with an id and an effect or setup
    function.

so the plugin imported cleanly, registered nothing, and every session logged a
load failure. The contract below is what the loader enforces, cross-checked
against the plugins that do load on this machine.
"""
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agi_memory import hooks  # noqa: E402


def _default_export_object(src: str) -> str:
    """The body of `export default { ... }`, brace-matched."""
    start = src.index("export default {")
    depth, i = 0, start + len("export default {") - 1
    while True:
        i += 1
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]


class LoaderContractTests(unittest.TestCase):
    """What opencode's loader validates, per its own error message."""

    def setUp(self):
        self.src = hooks.OPENCODE_PLUGIN_TEMPLATE

    def test_default_export_is_an_object_with_id_and_setup(self):
        # A bare `export const X = async () => {}` is what broke it.
        self.assertNotRegex(self.src, r"export\s+const\s+\w+\s*=\s*async\s*\(")
        body = _default_export_object(self.src)
        self.assertRegex(body, r"id:\s*\"agi-memory\"")
        self.assertRegex(body, r"async\s+setup\s*\(\s*ctx\s*\)")

    def test_id_is_the_marker_uninstall_gates_on(self):
        # uninstall used to key on the string "AgiMemoryPlugin", which this
        # template no longer contains -- it would have refused to remove our
        # own plugin file. The plugin id is required by the loader, so it is the
        # marker that is always present.
        self.assertIn('id: "agi-memory"', self.src)
        self.assertIn('id: "agi-memory"', hooks._PLUGIN_MARKERS)

    def test_uses_only_hook_names_this_build_implements(self):
        # Each of these appears in opencode's own loader; "compaction" and
        # execute.after are the ones a doc-driven rewrite would have dropped.
        for name in ('"context"', '"prompt"', '"compaction"'):
            self.assertIn(f"hook?.({name}", self.src, name)
        self.assertIn('hook?.("execute.after"', self.src)

    def test_every_ctx_access_is_optional_chained(self):
        # An unimplemented hook must be a no-op, never a throw that takes the
        # editor session down with it.
        for call in re.findall(r"ctx\.[a-z]+\??\.[a-z]+\?\.\(", self.src):
            self.assertIn("?.", call)

    def test_no_bare_plugin_function_default(self):
        # `export default <identifier>` is how a function sneaks back in.
        self.assertRegex(self.src, r"export default \{", )
        self.assertNotRegex(self.src, r"export default \w")

    def test_placeholders_survive(self):
        self.assertIn("@@PY@@", self.src)
        self.assertIn("@@HOOKS_PY@@", self.src)

    def test_no_stray_backslashes(self):
        # The template is a Python string literal; an unescaped backslash is a
        # syntax error or a corrupted JS escape.
        self.assertNotIn("\\", self.src.replace("@@PY@@", "").replace("@@HOOKS_PY@@", ""))

    def test_pre_tool_is_deliberately_absent(self):
        # execute.before only sees the tool input -- no channel into the model,
        # so a pre-tool recall line would have nowhere to go.
        self.assertNotIn('"execute.before"', self.src)
        self.assertIn("No execute.before", self.src)


class InstalledFileTests(unittest.TestCase):
    """install_opencode_plugin must write a file the loader would accept."""

    def test_written_file_satisfies_the_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(Path, "home", return_value=Path(tmp)):
                ok, msg = hooks.install_opencode_plugin(
                    scope="user", py_path="/usr/bin/python3")
                self.assertTrue(ok, msg)
                target = Path(hooks.opencode_plugin_path("user"))
                # Everything below must touch the temp home. Computing the path
                # outside the patch writes to the real ~/.config and silently
                # replaces the user's installed plugin.
                self.assertTrue(str(target).startswith(tmp), target)
                written = target.read_text()
        body = _default_export_object(written)
        self.assertRegex(body, r"id:\s*\"agi-memory\"")
        self.assertRegex(body, r"async\s+setup\s*\(\s*ctx\s*\)")
        self.assertIn("/usr/bin/python3", written)

    def test_uninstall_removes_our_own_file(self):
        # The regression: the ownership marker moved to the plugin id, and a
        # stale check would leave the file behind while claiming it was foreign.
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(Path, "home", return_value=Path(tmp)):
                hooks.install_opencode_plugin(scope="user", py_path="/usr/bin/python3")
                target = Path(hooks.opencode_plugin_path("user"))
                self.assertTrue(str(target).startswith(tmp), target)
                ok, _ = hooks.uninstall_opencode_plugin(scope="user")
                self.assertTrue(ok)
                self.assertFalse(target.exists())

    def test_uninstall_refuses_a_foreign_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(Path, "home", return_value=Path(tmp)):
                target = Path(hooks.opencode_plugin_path("user"))
                self.assertTrue(str(target).startswith(tmp), target)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("export default { id: 'someone-else' }")
                ok, msg = hooks.uninstall_opencode_plugin(scope="user")
            self.assertFalse(ok)
            self.assertIn("Refusing", msg)
            self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
