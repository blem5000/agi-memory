"""A vault must be its own git root, and two processes must not sync it at once.

Both tests are red-first: they assert the behaviour that was missing when a sync
resolved onto the app repository, removed its origin, added an unrelated one,
renamed the branch, and then recorded 101 tracked files as deleted on main.

The lock test exists because `threading.Lock` was the only mutual exclusion in
`sync()`, and fourteen separate processes each held it happily. A thread lock is
invisible across processes, which is precisely the case that mattered.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from agi_memory import config  # noqa: E402
from agi_memory import sync  # noqa: E402


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=path)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "add", "-A", cwd=path)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base", cwd=path)


class ContainmentTests(unittest.TestCase):
    def test_refuses_a_vault_inside_another_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "app"
            _init_repo(repo)
            vault = repo / "memory"          # a vault inside a checkout
            vault.mkdir()
            with self.assertRaises(RuntimeError) as ctx:
                config.assert_vault_isolation(vault)
            self.assertIn("inside the git repository", str(ctx.exception))
            self.assertIn("AGI_MEMORY", str(ctx.exception),
                          "the error must name a variable the user can unset")

    def test_refuses_a_vault_that_contains_another_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            vault.mkdir()
            _init_repo(vault / "checkout")     # a checkout wrapped by the vault
            with self.assertRaises(RuntimeError) as ctx:
                config.assert_vault_isolation(vault)
            self.assertIn("contains the git repository", str(ctx.exception))

    def test_allows_a_standalone_vault(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            _init_repo(vault)
            config.assert_vault_isolation(vault)     # must not raise

    def test_allows_a_plain_directory_that_is_not_a_repo_yet(self):
        with tempfile.TemporaryDirectory() as tmp:
            fresh = Path(tmp) / "brand-new-vault"
            config.assert_vault_isolation(fresh)     # must not raise

    def test_follows_symlinks_before_deciding(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "app"
            _init_repo(repo)
            real = repo / "memory"
            real.mkdir()
            link = Path(tmp) / "link-to-vault"
            link.symlink_to(real)
            with self.assertRaises(RuntimeError):
                config.assert_vault_isolation(link)

    def test_recognises_a_worktree_whose_git_is_a_file(self):
        # A linked worktree has .git as a *file*. A check that assumed a
        # directory would call an isolated worktree a non-repository.
        with tempfile.TemporaryDirectory() as tmp:
            main = Path(tmp) / "main"
            _init_repo(main)
            wt = Path(tmp) / "wt"
            _git("worktree", "add", "-q", str(wt), "-b", "side", cwd=main)
            self.assertTrue((wt / ".git").is_file(), "expected a .git file")
            config.assert_vault_isolation(wt)     # its own root: must not raise

    def test_sync_refuses_rather_than_committing_into_a_checkout(self):
        # The end-to-end shape of the incident, with the repo's history checked
        # before and after: nothing may be committed and no file may disappear.
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            _init_repo(app)
            decoy = app / "rules.md"
            decoy.write_text("keep me\n", encoding="utf-8")
            _git("-c", "user.name=t", "-c", "user.email=t@t", "add", "-A", cwd=app)
            _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "decoy", cwd=app)
            before = _git("rev-parse", "HEAD", cwd=app).stdout.strip()
            vault = app / "memory"
            vault.mkdir()
            with self.assertRaises(RuntimeError):
                sync.sync(vault_dir=vault, push=False, pull=False)
            self.assertTrue(decoy.exists(), "a decoy file went missing")
            after = _git("rev-parse", "HEAD", cwd=app).stdout.strip()
            self.assertEqual(before, after, "the checkout's HEAD moved")
            names = _git("show", "--name-only", "--format=", "HEAD", cwd=app).stdout
            self.assertIn("rules.md", names)


class ReceiptTests(unittest.TestCase):
    """The ledger must not live in the vault.

    It did, once. Two consequences, both found by the two-machine test rather
    than by inspection: a file rewritten on every sync means every sync commits,
    and a receipt appended after the commit leaves the working tree dirty, so the
    next `git pull --rebase` refuses and two machines stop converging.
    """

    def test_receipts_are_written_outside_the_vault(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data, vault = root / "data", root / "vault"
            vault.mkdir()
            _init_repo(vault)
            env = {**os.environ, "AGI_MEMORY_DIR": str(data), "AGI_MEMORY_VAULT": str(vault)}
            code = ("import sys; sys.path.insert(0, %r)\n"
                    "from agi_memory import sync\n"
                    "from pathlib import Path\n"
                    "v = Path(%r)\n"
                    "sync._receipt(v, ['add', '-A'], 'staged')\n"
                    "print(sorted(p.name for p in v.iterdir()))\n"
                    "print(sync.receipts_path())\n" % (str(REPO / "src"), str(vault)))
            out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                 text=True, timeout=60, env=env)
            self.assertEqual(0, out.returncode, out.stderr)
            lines = out.stdout.strip().splitlines()
            self.assertNotIn("write-receipts.jsonl", lines[0],
                             "the receipt file was written into the vault")
            self.assertTrue(lines[1].endswith("write-receipts.jsonl"))
            self.assertTrue(str(vault) not in lines[1],
                            "the ledger must be outside every git repository")

    def test_a_sync_leaves_the_vault_working_tree_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            _init_repo(vault)
            (vault / "observations.jsonl").write_text('{"id": 1, "text": "a"}\n', encoding="utf-8")
            _git("-c", "user.name=t", "-c", "user.email=t@t", "add", "-A", cwd=vault)
            _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed", cwd=vault)
            env = {**os.environ, "AGI_MEMORY_DIR": str(root / "data"),
                   "AGI_MEMORY_VAULT": str(vault)}
            code = ("import sys; sys.path.insert(0, %r)\n"
                    "from agi_memory import sync\n"
                    "print(sync.sync(push=False, pull=False)['status'])\n" % str(REPO / "src"))
            out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                 text=True, timeout=180, env=env)
            self.assertEqual(0, out.returncode, out.stderr)
            # A dirty tree is what made `pull --rebase` refuse on the next run.
            status = _git("status", "--porcelain", cwd=vault).stdout.strip()
            self.assertEqual("", status,
                             f"sync left the vault dirty, so the next rebase would fail: {status}")


class ProcessLockTests(unittest.TestCase):
    """The lock must exclude a *separate process*, which is the case that
    mattered: fourteen copies of the suite each held a `threading.Lock`."""

    def setUp(self):
        # The lock now lives in the data directory, so every test points that at
        # its own temp dir rather than at the developer's real one.
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._env = patch.dict(os.environ, {"AGI_MEMORY_DIR": self._tmp.name})
        self._env.start()
        self.addCleanup(self._env.stop)

    def _try_acquire_in_child(self, vault: Path) -> bool:
        """Run a real second process and report whether it got the lock."""
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "from agi_memory import vault_lock\n"
            "with vault_lock.acquire(%r, timeout=2) as lk:\n"
            "    print('GOT' if lk.held else 'BUSY')\n" % (str(REPO / "src"), str(vault))
        )
        out = subprocess.run([sys.executable, "-c", code],
                             capture_output=True, text=True, timeout=60,
                             env={**os.environ})
        return "GOT" in out.stdout

    def test_a_second_process_is_refused_while_held(self):
        from agi_memory import vault_lock
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            vault.mkdir()
            with vault_lock.acquire(vault) as held:
                self.assertTrue(held.held)
                self.assertFalse(self._try_acquire_in_child(vault),
                                 "a second process took a held lock")

    def test_a_second_process_succeeds_once_released(self):
        from agi_memory import vault_lock
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            vault.mkdir()
            with vault_lock.acquire(vault) as held:
                self.assertTrue(held.held)
            # Released: the next writer must not be blocked by a stale file, or
            # every later sync would silently skip.
            self.assertTrue(self._try_acquire_in_child(vault),
                            "lock was not released -- later syncs would all skip")

    def test_two_different_vaults_do_not_contend(self):
        from agi_memory import vault_lock
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a", Path(tmp) / "b"
            a.mkdir()
            b.mkdir()
            with vault_lock.acquire(a) as held_a:
                self.assertTrue(held_a.held)
                with vault_lock.acquire(b, timeout=2) as held_b:
                    self.assertTrue(held_b.held,
                                    "one vault's lock blocked an unrelated vault")

    def test_the_lock_is_never_inside_a_git_repository(self):
        from agi_memory import vault_lock
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            _init_repo(vault)
            with vault_lock.acquire(vault) as held:
                self.assertTrue(held.held)
                self.assertNotIn(vault.resolve(), held.path.resolve().parents,
                                 "the lock file is inside the vault and git will commit it")
                self.assertFalse((vault / ".agi-vault.lock").exists())

    def test_a_stale_lock_from_a_dead_process_is_reclaimed(self):
        from agi_memory import vault_lock
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            vault.mkdir()
            stale = vault_lock.lock_path(vault)
            stale.write_text("999999")     # as if a process died holding it
            old = time.time() - vault_lock.STALE_SECONDS - 60
            os.utime(stale, (old, old))
            with vault_lock.acquire(vault) as held:
                self.assertTrue(held.held, "a stale lock wedged the vault forever")
            self.assertFalse(stale.exists())

    def test_lock_state_is_reportable_for_doctor(self):
        from agi_memory import vault_lock
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            vault.mkdir()
            self.assertEqual("free", vault_lock.status(vault))
            with vault_lock.acquire(vault):
                self.assertTrue(vault_lock.status(vault).startswith("held"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
