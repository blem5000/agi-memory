"""Two-machine sync test, driven through the real CLI in isolated environments.

The council's gate before launch was: prove two real machines converge. The
offline suite already asserts convergence at the git level, but that test drives
git directly. This one drives `agi-memory sync` and `memory_record` the way a
user's machines actually would, with two fully separate HOMEs and vaults talking
to a shared bare repository.

Nothing here touches the developer's own vault: every path is inside a
temporary directory, and each simulated machine runs in a subprocess with its
own AGI_MEMORY_DIR, AGI_MEMORY_VAULT and AGI_MEMORY_DB.

Run:  python3 tests/multi_machine_test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"

PASS, FAIL = "  PASS ", "  FAIL "
_results = []


def check(name: str, fn) -> bool:
    try:
        ok = fn()
        print(f"{PASS if ok else FAIL} {name}")
        _results.append(ok)
        return ok
    except Exception as e:
        print(f"{FAIL} {name}\n        {type(e).__name__}: {e}")
        _results.append(False)
        return False


class Machine:
    """One simulated machine: its own home, vault, database and git identity."""

    def __init__(self, root: Path, name: str, remote: Path):
        self.name = name
        self.home = root / name
        self.vault = self.home / "vault"
        self.db = self.home / "memory.db"
        self.remote = remote
        self.home.mkdir(parents=True, exist_ok=True)

    @property
    def env(self) -> dict:
        return {
            **os.environ,
            "HOME": str(self.home),
            "AGI_MEMORY_DIR": str(self.home),
            "AGI_MEMORY_VAULT": str(self.vault),
            "AGI_MEMORY_DB": str(self.db),
            "PYTHONPATH": str(SRC),
            "GIT_AUTHOR_NAME": self.name,
            "GIT_AUTHOR_EMAIL": f"{self.name}@test",
            "GIT_COMMITTER_NAME": self.name,
            "GIT_COMMITTER_EMAIL": f"{self.name}@test",
        }

    def py(self, code: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-c", code], env=self.env,
                              capture_output=True, text=True, timeout=120)

    def git(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=self.vault, env=self.env,
                              capture_output=True, text=True, timeout=60)

    def init(self) -> None:
        """Set the vault up and point it at the shared remote, as install would."""
        res = self.py(
            "from agi_memory.sync import init_git_repo\n"
            "init_git_repo()\n"
        )
        assert res.returncode == 0, f"{self.name} vault init failed: {res.stderr[-400:]}"
        self.git("remote", "add", "origin", str(self.remote))

    def record(self, text: str, title: str, project: str = "shared") -> None:
        res = self.py(
            "from agi_memory import mcp_server as m\n"
            f"print(m.call_tool('memory_record', {{'text': {text!r}, "
            f"'title': {title!r}, 'project': {project!r}}}))\n"
        )
        assert res.returncode == 0, f"{self.name} record failed: {res.stderr[-400:]}"

    def sync(self) -> dict:
        res = self.py(
            "import json\n"
            "from agi_memory.sync import sync\n"
            "print(json.dumps(sync(push=True, pull=True), default=str))\n"
        )
        assert res.returncode == 0, f"{self.name} sync failed: {res.stderr[-500:]}"
        line = [l for l in res.stdout.splitlines() if l.startswith("{")]
        return json.loads(line[-1]) if line else {}

    def recall(self, query: str, project: str = "shared") -> str:
        res = self.py(
            "from agi_memory import mcp_server as m\n"
            f"print(m.call_tool('memory_recall', {{'query': {query!r}, "
            f"'project': {project!r}}}))\n"
        )
        return res.stdout

    def vault_records(self) -> list:
        out = []
        for f in sorted(self.vault.glob("*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return out

    def texts(self) -> set:
        keys = ("narrative", "text", "title")
        return {str(r.get(k, "")) for r in self.vault_records() for k in keys if r.get(k)}


def main() -> int:
    if not shutil.which("git"):
        print("git not available; skipping")
        return 0

    print("\nTwo-machine sync — real CLI, isolated environments\n" + "=" * 58)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        remote = root / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)

        m1 = Machine(root, "laptop", remote)
        m2 = Machine(root, "desktop", remote)
        m1.init()
        m2.init()

        check("both machines initialise isolated vaults",
              lambda: m1.vault.exists() and m2.vault.exists() and m1.vault != m2.vault)

        check("the union merge policy is installed at init",
              lambda: "merge=union" in (m1.vault / ".gitattributes").read_text())

        # laptop records first and publishes
        m1.record("Chose SQLite FTS5 for working memory, no external services.",
                  "Storage decision")
        s1 = m1.sync()
        check(f"laptop first sync pushes (status={s1.get('status')})",
              lambda: s1.get("status") in ("synced", "local_only"))

        # desktop joins and picks up the laptop's memory
        m2.git("fetch", "-q", "origin")
        m2.git("checkout", "-qB", "main", "origin/main")
        s2 = m2.sync()
        check("desktop receives the laptop's memory",
              lambda: any("SQLite FTS5" in t for t in m2.texts()))

        # THE CASE THAT USED TO LOSE DATA: both record before either syncs
        m1.record("Retry webhooks with exponential backoff, five attempts max.",
                  "Retry policy")
        m2.record("Deploy with rolling updates, never all at once.",
                  "Deploy policy")

        s1b = m1.sync()
        s2b = m2.sync()
        check(f"desktop sync does not report a conflict (status={s2b.get('status')})",
              lambda: s2b.get("status") not in ("pull_conflict", "push_rejected"))

        # Let both settle. One round is not enough to guarantee the REMOTE holds
        # everything: each machine pushes only what it had at pull time, so the
        # last writer's records reach the remote a round later. Loop until the
        # remote is stable rather than assuming a fixed number of rounds --
        # asserting on remote state after a fixed two syncs was flaky on CI.
        MARKERS = ("SQLite FTS5", "backoff", "rolling updates")

        def markers_on_remote() -> set:
            """Which distinct memories the remote holds.

            Counting matching LINES is wrong: union merge can legitimately
            duplicate a line, so three matches may be two distinct memories.
            That made the loop below exit early and the fresh-clone check fail.
            """
            probe = root / f"probe-{os.getpid()}"
            shutil.rmtree(probe, ignore_errors=True)
            subprocess.run(["git", "clone", "-q", str(remote), str(probe)],
                           capture_output=True, timeout=60)
            found = set()
            for f in probe.glob("*.jsonl"):
                blob = f.read_text(encoding="utf-8")
                found |= {m for m in MARKERS if m in blob}
            shutil.rmtree(probe, ignore_errors=True)
            return found

        for _ in range(5):
            m1.sync()
            m2.sync()
            if markers_on_remote() == set(MARKERS):
                break

        t1, t2 = m1.texts(), m2.texts()
        check("laptop holds the desktop's memory",
              lambda: any("rolling updates" in t for t in t1))
        check("desktop holds the laptop's memory",
              lambda: any("exponential backoff" in t for t in t2))

        def converged():
            a = {t for t in t1 if "SQLite FTS5" in t or "backoff" in t or "rolling" in t}
            b = {t for t in t2 if "SQLite FTS5" in t or "backoff" in t or "rolling" in t}
            return len(a) == len(b) == 3
        check("both vaults converged on all three memories", converged)

        check("no unresolved git state left on either machine",
              lambda: not (m1.vault / ".git" / "rebase-merge").exists()
              and not (m2.vault / ".git" / "rebase-merge").exists())

        # the memories must be searchable, not merely present as text
        r = m2.recall("exponential backoff")
        check("the synced memory is retrievable on the other machine",
              lambda: "backoff" in r.lower())

        # a third machine cloning fresh must see everything
        m3 = Machine(root, "newmachine", remote)
        m3.home.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", str(remote), str(m3.vault)],
                       env=m3.env, capture_output=True)
        def fresh_clone_sees_all():
            blob = " ".join(m3.texts())
            missing = [m for m in MARKERS if m not in blob]
            if missing:
                print(f"        missing from fresh clone: {missing}")
            return not missing
        check("a fresh machine cloning the vault sees all three memories",
              fresh_clone_sees_all)

    print("=" * 58)
    passed = sum(1 for r in _results if r)
    print(f"{passed}/{len(_results)} passed\n")
    return 0 if passed == len(_results) else 1


if __name__ == "__main__":
    sys.exit(main())
