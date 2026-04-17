"""Cross-platform single-instance lock for the GUI application.

Uses file-level advisory locks so a second launch can detect an existing
instance and exit cleanly. Stale locks from crashed processes are
released automatically by the OS when the file handle is closed.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from lib.app_storage import get_user_config_dir


_LOCK_FILENAME = "instance.lock"


def default_lock_path() -> str:
    return os.path.join(get_user_config_dir(), _LOCK_FILENAME)


class SingleInstanceLock:
    """Acquire an exclusive OS-level lock on a file.

    `acquire()` returns True if this process now owns the lock, False if
    another process already holds it. `release()` drops the lock and
    closes the file handle. The lock is also released automatically when
    the process exits.
    """

    def __init__(self, lock_path: Optional[str] = None):
        self._lock_path = lock_path or default_lock_path()
        self._fh = None
        self._acquired = False

    @property
    def lock_path(self) -> str:
        return self._lock_path

    @property
    def acquired(self) -> bool:
        return self._acquired

    def acquire(self) -> bool:
        if self._acquired:
            return True

        os.makedirs(os.path.dirname(self._lock_path), exist_ok=True)

        try:
            fh = open(self._lock_path, "a+")
        except OSError:
            return False

        if os.name == "nt":
            locked = self._lock_windows(fh)
        else:
            locked = self._lock_posix(fh)

        if not locked:
            try:
                fh.close()
            except OSError:
                pass
            return False

        self._fh = fh
        self._acquired = True
        try:
            fh.seek(0)
            fh.truncate()
            fh.write(str(os.getpid()))
            fh.flush()
        except OSError:
            pass
        return True

    def release(self) -> None:
        if not self._acquired or self._fh is None:
            return

        try:
            if os.name == "nt":
                self._unlock_windows(self._fh)
            else:
                self._unlock_posix(self._fh)
        except OSError:
            pass

        try:
            self._fh.close()
        except OSError:
            pass

        self._fh = None
        self._acquired = False

    def __enter__(self) -> "SingleInstanceLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()

    @staticmethod
    def _lock_posix(fh) -> bool:
        import fcntl

        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (OSError, BlockingIOError):
            return False

    @staticmethod
    def _unlock_posix(fh) -> None:
        import fcntl

        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _lock_windows(fh) -> bool:
        import msvcrt

        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    @staticmethod
    def _unlock_windows(fh) -> None:
        import msvcrt

        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass


__all__ = ["SingleInstanceLock", "default_lock_path"]
