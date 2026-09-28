"""Cross-process mutual exclusion for vault writes.

`sync()` guarded itself with `threading.Lock`, which is invisible between
processes. Fourteen separate `test_offline.py` processes were observed running
at once, each believing it held the lock, each able to `git add -A` and commit
in the same directory. A thread lock cannot fix that and its presence is
misleading, so the real lock is a file lock: `fcntl.flock` where it exists,
`msvcrt.locking` on Windows, and a no-op fallback that at least says so.

Deliberately *not* a permission layer: it prevents two writers from interleaving
and nothing else. It never blocks a read, and it never decides whether a write
was a good idea.
"""
from __future__ import annotations

import hashlib
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

try:
    import fcntl
except ImportError:      # Windows
    fcntl = None
try:
    import msvcrt
except ImportError:
    msvcrt = None

# The lock lives in the data directory, NOT in the vault. It was in the vault
# once, and `git add -A` committed it: a file created and deleted by every sync
# both dirties the working tree -- so the next `git pull --rebase` refuses to
# run -- and puts a lock file in the user's synced vault.
#
# The name is derived from the resolved vault path, so two vaults do not contend
# with each other while the same vault is still serialised across processes.
LOCK_PREFIX = ".agi-vault-"
# A crashed holder must not wedge the vault forever. Generous, because a real
# sync is seconds; long enough that a slow push is never stolen from.
STALE_SECONDS = 300
POLL_SECONDS = 0.25
# How long a writer waits before reporting "locked" and skipping. A sync holds
# this for seconds, so a longer wait only delays the message saying so.
DEFAULT_TIMEOUT = 30.0


def lock_path(vault_dir: Path | str) -> Path:
    """Where the lock for this vault lives. Never inside a git repository."""
    from agi_memory.config import get_data_dir
    try:
        resolved = str(Path(vault_dir).expanduser().resolve())
    except OSError:
        resolved = str(vault_dir)
    tag = hashlib.sha256(resolved.encode("utf-8", "replace")).hexdigest()[:16]
    return get_data_dir() / f"{LOCK_PREFIX}{tag}.lock"


class _Lock:
    def __init__(self, path: Path):
        self.path = path
        self.held = False
        self._fd: Optional[int] = None
        self._fallback = False

    def _break_if_stale(self) -> None:
        try:
            age = time.time() - self.path.stat().st_mtime
        except OSError:
            return
        if age > STALE_SECONDS:
            # Left behind by a process that died mid-sync. Removing the file is
            # safe because the kernel lock died with it.
            try:
                self.path.unlink()
            except OSError:
                pass

    def acquire(self, timeout: float = DEFAULT_TIMEOUT) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            self._break_if_stale()
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o644)
            except FileExistsError:
                if time.monotonic() >= deadline:
                    return False      # a live holder has held it past `timeout`
                time.sleep(POLL_SECONDS)
                continue
            self._fd = fd
            self._touch()
            self.held = True
            return True

    def _touch(self) -> None:
        try:
            os.utime(str(self.path), None)
        except OSError:
            pass

    def release(self) -> None:
        if not self.held:
            return
        self.held = False
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        try:
            self.path.unlink()
        except OSError:
            pass


@contextmanager
def acquire(vault_dir: Path | str, timeout: float = DEFAULT_TIMEOUT) -> Iterator[_Lock]:
    """Hold the vault lock for the duration of the block.

    `lock.held` is False when the wait timed out; the caller decides what that
    means. A sync skips rather than blocks, because a second concurrent sync has
    nothing to add.
    """
    lock = _Lock(lock_path(vault_dir))
    got = lock.acquire(timeout)
    try:
        yield lock
    finally:
        if got:
            lock.release()


def status(vault_dir: Path | str | None = None) -> str:
    """Human-readable lock state, for `verify` and `doctor`."""
    from agi_memory.config import get_vault_dir
    try:
        path = lock_path(vault_dir or get_vault_dir())
    except Exception:
        return "unknown"
    if not path.exists():
        return "free"
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return "held"
    return f"held ({int(age)}s ago)"
