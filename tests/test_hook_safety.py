"""Hook safety: bounded reentrancy, a sanitised child env, no pre-commit.

Three defects, one incident. A pre-commit hook ran the offline suite; the suite
committed inside a worktree; that commit re-fired the hook; the tree fanned out
to 14+ concurrent copies of the suite, and each generation rewrote the
repository's .git/config on the way past. One commit reached main and deleted
20+ tracked files.

These tests pin the three fixes. The hermeticity one is deliberately written so
it is red before the fix and green after -- from inside the repository, where
git can actually walk up and find it, rather than from a temp directory where
git already fails either way and the assertion proves nothing.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from agi_memory import hooks  # noqa: E402


class ReentrancyTests(unittest.TestCase):
    def test_pre_commit_is_a_no_op_inside_a_hook_chain(self):
        with mock.patch.dict(os.environ, {"AGI_MEMORY_HOOK": "1"}), \
             mock.patch.object(hooks.subprocess, "call") as call:
            hooks.hook_pre_commit()
        call.assert_not_called()

    def test_pre_commit_still_runs_when_invoked_by_hand(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(hooks.subprocess, "call", return_value=0) as call:
            hooks.hook_pre_commit()
        self.assertTrue(call.called, "the manual check must still work")

    def test_pre_commit_marks_the_chain_for_its_children(self):
        seen = {}

        def fake_call(cmd, **kw):
            seen.update(kw.get("env") or {})
            return 0

        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(hooks.subprocess, "call", fake_call):
            hooks.hook_pre_commit()
        self.assertEqual("1", seen.get("AGI_MEMORY_HOOK"),
                         "a hook fired by the suite must not re-enter the suite")

    def test_validate_script_bails_when_already_inside(self):
        script = REPO / "hooks" / "validate-offline.sh"
        body = script.read_text(encoding="utf-8")
        self.assertIn("AGI_MEMORY_HOOK", body)
        # The bound has to be a guard that exits, not a comment.
        self.assertRegex(body, r'if \[ -n "\$\{AGI_MEMORY_HOOK:-\}" \]; then')


class DetachedEnvTests(unittest.TestCase):
    def test_child_does_not_inherit_a_stale_vault_path(self):
        # The defect: the child outlived the process that pointed AGI_MEMORY_VAULT
        # at a temp dir, and kept naming a directory that no longer existed.
        with mock.patch.dict(os.environ, {
                "AGI_MEMORY_VAULT": "/tmp/does-not-exist-any-more/vault",
                "AGI_MEMORY_DIR": "/tmp/does-not-exist-any-more",
                "AGI_MEMORY_DB": "/tmp/does-not-exist-any-more/m.db",
                "PATH": "/usr/bin:/bin"}):
            with mock.patch.object(hooks.subprocess, "Popen") as popen:
                hooks._spawn_detached(["/bin/true"])
        env = popen.call_args.kwargs.get("env") or {}
        for leaked in ("AGI_MEMORY_VAULT", "AGI_MEMORY_DIR", "AGI_MEMORY_DB"):
            self.assertNotIn(leaked, env, f"{leaked} leaked to the detached child")
        self.assertEqual("1", env.get("AGI_MEMORY_HOOK"))
        # Everything not ours is preserved, or the child cannot find python.
        self.assertEqual("/usr/bin:/bin", env.get("PATH"))

    def test_unrelated_variables_survive(self):
        with mock.patch.dict(os.environ, {"HOME": "/Users/x", "AGENT_MEMORY_PROJECT": "p"}):
            with mock.patch.object(hooks.subprocess, "Popen") as popen:
                hooks._spawn_detached(["/bin/true"])
        env = popen.call_args.kwargs.get("env") or {}
        self.assertEqual("/Users/x", env.get("HOME"))
        # AGENT_MEMORY_ is the legacy spelling and must not be mistaken for ours.
        self.assertEqual("p", env.get("AGENT_MEMORY_PROJECT"))


class HermeticityTests(unittest.TestCase):
    """Name-resolution isolation: a fixture must not be able to name the real repo.

    Both mechanisms below were measured before being asserted. The ceiling has
    unintuitive semantics: it must name an *ancestor* of the repository. Setting
    it to the fixture's own path, or to a directory above the repo, does not stop
    discovery -- only naming the repo root does.
    """

    def _resolve(self, cwd, env=None):
        out = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=cwd,
                             env=env or os.environ, capture_output=True, text=True)
        return out.stdout.strip()

    def test_a_fixture_inside_the_repo_would_otherwise_reach_it(self):
        # The control: without isolation, git walks up and finds the real repo.
        # Without this, the assertions below could pass vacuously.
        with tempfile.TemporaryDirectory(dir=str(REPO)) as inside:
            self.assertIn(str(REPO), self._resolve(inside))

    def test_ceiling_naming_the_repo_root_blocks_discovery(self):
        with tempfile.TemporaryDirectory(dir=str(REPO)) as inside:
            got = self._resolve(inside, {**os.environ,
                                         "GIT_CEILING_DIRECTORIES": str(REPO)})
        self.assertNotIn(str(REPO), got)

    def test_ceiling_naming_the_fixture_does_nothing(self):
        # Recorded because it is the value everyone tries first, and it does not
        # work: git still finds the repository above it.
        with tempfile.TemporaryDirectory(dir=str(REPO)) as inside:
            got = self._resolve(inside, {**os.environ,
                                         "GIT_CEILING_DIRECTORIES": inside})
        self.assertIn(str(REPO), got,
                      "if this ever starts working, the test above needs rethinking")

    def test_hooks_can_be_neutralised_for_a_fixture_commit(self):
        # The mechanism the incident actually turned on: a commit inside a
        # fixture firing the real repository's pre-commit hook.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True,
                           capture_output=True)
            marker = root / "HOOK_RAN"
            hook = root / ".git" / "hooks" / "pre-commit"
            hook.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
            hook.chmod(0o755)
            ident = ["-c", "user.email=t@t", "-c", "user.name=t"]
            subprocess.run(["git", *ident, "commit", "-q", "--allow-empty", "-m", "x"],
                           cwd=root, check=True, capture_output=True)
            self.assertTrue(marker.exists(), "control: the hook should have run")
            marker.unlink()
            subprocess.run(["git", *ident, "-c", "core.hooksPath=/dev/null",
                            "commit", "-q", "--allow-empty", "-m", "y"],
                           cwd=root, check=True, capture_output=True)
            self.assertFalse(marker.exists(),
                             "core.hooksPath=/dev/null must stop a fixture commit "
                             "from firing hooks")


class InstallTests(unittest.TestCase):
    def test_no_pre_commit_hook_is_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            ok, _ = hooks.install_git_hooks(target_dir=root, py_path="/usr/bin/python3")
            self.assertTrue(ok)
            names = {p.name for p in (root / ".git" / "hooks").iterdir()}
            self.assertNotIn("pre-commit", names)
            self.assertIn("post-commit", names)
            self.assertIn("pre-push", names)

    def test_a_stale_pre_commit_from_an_earlier_version_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hooks_dir = root / ".git" / "hooks"
            hooks_dir.mkdir(parents=True)
            stale = hooks_dir / "pre-commit"
            stale.write_text('#!/usr/bin/env bash\n"py" "/x/hooks.py" pre-commit\n')
            stale.chmod(0o755)
            hooks.install_git_hooks(target_dir=root, py_path="/usr/bin/python3")
            self.assertFalse(stale.exists(),
                             "leaving it would keep the recursion entry point installed")

    def test_a_foreign_pre_commit_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hooks_dir = root / ".git" / "hooks"
            hooks_dir.mkdir(parents=True)
            foreign = hooks_dir / "pre-commit"
            foreign.write_text("#!/usr/bin/env bash\nnpm test\n")
            hooks.install_git_hooks(target_dir=root, py_path="/usr/bin/python3")
            self.assertTrue(foreign.exists(), "not ours to delete")


class DoctorVisibilityTests(unittest.TestCase):
    """A pre-commit left by an earlier version must be visible in `doctor`.

    Otherwise the user believes the upgrade removed it, and the suite keeps
    running on every commit with nothing to say so.
    """

    def test_stale_pre_commit_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hooks_dir = root / ".git" / "hooks"
            hooks_dir.mkdir(parents=True)
            (hooks_dir / "pre-commit").write_text(
                '#!/usr/bin/env bash\n"py" "/x/hooks.py" pre-commit\n', encoding="utf-8")
            (hooks_dir / "post-commit").write_text(
                '#!/usr/bin/env bash\n"py" "/x/hooks.py" post-commit &\n', encoding="utf-8")
            got = hooks.git_hook_status(root)
        self.assertTrue(got["stale_pre_commit"])
        self.assertEqual(["post-commit"], got["installed"])

    def test_a_foreign_pre_commit_is_not_reported_as_ours(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hooks_dir = root / ".git" / "hooks"
            hooks_dir.mkdir(parents=True)
            (hooks_dir / "pre-commit").write_text("#!/usr/bin/env bash\nnpm test\n",
                                                  encoding="utf-8")
            got = hooks.git_hook_status(root)
        self.assertFalse(got["stale_pre_commit"])
        self.assertEqual([], got["installed"])

    def test_no_hooks_directory_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            got = hooks.git_hook_status(Path(tmp))
        self.assertEqual([], got["installed"])
        self.assertFalse(got["stale_pre_commit"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
