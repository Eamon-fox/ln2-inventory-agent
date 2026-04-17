"""Lock tests for app_gui.single_instance.SingleInstanceLock.

Exercises the acquire/release contract the GUI entry point depends on:
first acquire succeeds, a second acquire on the same path fails while
the first is held, and releasing lets a fresh acquire succeed again.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from app_gui.single_instance import SingleInstanceLock, default_lock_path


class SingleInstanceLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.lock_path = os.path.join(self._tmp.name, "nested", "instance.lock")

    def test_first_acquire_creates_lock_file_and_records_pid(self) -> None:
        lock = SingleInstanceLock(self.lock_path)
        self.addCleanup(lock.release)

        self.assertTrue(lock.acquire())
        self.assertTrue(lock.acquired)
        self.assertTrue(os.path.exists(self.lock_path))

        with open(self.lock_path, "r", encoding="utf-8") as fh:
            content = fh.read().strip()
        self.assertEqual(content, str(os.getpid()))

    def test_second_acquire_on_same_path_fails_while_first_holds(self) -> None:
        first = SingleInstanceLock(self.lock_path)
        self.addCleanup(first.release)
        self.assertTrue(first.acquire())

        second = SingleInstanceLock(self.lock_path)
        self.addCleanup(second.release)
        self.assertFalse(second.acquire())
        self.assertFalse(second.acquired)

    def test_release_allows_subsequent_acquire(self) -> None:
        first = SingleInstanceLock(self.lock_path)
        self.assertTrue(first.acquire())
        first.release()
        self.assertFalse(first.acquired)

        second = SingleInstanceLock(self.lock_path)
        self.addCleanup(second.release)
        self.assertTrue(second.acquire())

    def test_context_manager_releases_on_exit(self) -> None:
        with SingleInstanceLock(self.lock_path) as lock:
            self.assertTrue(lock.acquired)

        fresh = SingleInstanceLock(self.lock_path)
        self.addCleanup(fresh.release)
        self.assertTrue(fresh.acquire())

    def test_default_lock_path_lives_under_user_config_dir(self) -> None:
        from lib.app_storage import get_user_config_dir

        path = default_lock_path()
        self.assertTrue(path.startswith(get_user_config_dir()))
        self.assertTrue(path.endswith("instance.lock"))


if __name__ == "__main__":
    unittest.main()
