"""Tests for lib.plan_store.PlanStore."""

import threading
import unittest

from lib.plan_store import PlanStore


def _item(action="takeout", record_id=1, position=5, **extra):
    item = {"action": action, "record_id": record_id, "position": position,
            "box": 1, "label": "test", "source": "human"}
    item.update(extra)
    return item


class TestPlanStoreBasic(unittest.TestCase):

    def test_empty_store(self):
        store = PlanStore()
        self.assertEqual(0, store.count())
        self.assertEqual([], store.list_items())
        self.assertFalse(store.has_rollback())

    def test_add_and_list(self):
        store = PlanStore()
        store.add([_item()])
        self.assertEqual(1, store.count())
        items = store.list_items()
        self.assertEqual("takeout", items[0]["action"])

    def test_list_returns_deepcopy(self):
        store = PlanStore()
        store.add([_item()])
        items = store.list_items()
        items[0]["action"] = "MUTATED"
        self.assertEqual("takeout", store.list_items()[0]["action"])

    def test_dedup_replaces(self):
        store = PlanStore()
        store.add([_item(label="v1")])
        store.add([_item(label="v2")])
        self.assertEqual(1, store.count())
        self.assertEqual("v2", store.list_items()[0]["label"])

    def test_dedup_different_keys(self):
        store = PlanStore()
        store.add([_item(record_id=1), _item(record_id=2)])
        self.assertEqual(2, store.count())

    def test_add_no_dedup(self):
        store = PlanStore()
        store.add([_item()], deduplicate=False)
        store.add([_item()], deduplicate=False)
        self.assertEqual(2, store.count())


class TestPlanStoreRemove(unittest.TestCase):

    def test_remove_by_index(self):
        store = PlanStore()
        store.add([_item(record_id=1), _item(record_id=2)])
        removed = store.remove_by_index(0)
        self.assertEqual(1, removed["record_id"])
        self.assertEqual(1, store.count())
        self.assertEqual(2, store.list_items()[0]["record_id"])

    def test_remove_by_index_invalid(self):
        store = PlanStore()
        store.add([_item()])
        self.assertIsNone(store.remove_by_index(5))
        self.assertIsNone(store.remove_by_index(-1))
        self.assertEqual(1, store.count())

    def test_remove_by_indices(self):
        store = PlanStore()
        store.add([_item(record_id=i) for i in range(5)])
        removed = store.remove_by_indices([0, 2, 4])
        self.assertEqual(3, removed)
        self.assertEqual(2, store.count())
        ids = [it["record_id"] for it in store.list_items()]
        self.assertEqual([1, 3], ids)

    def test_remove_by_key(self):
        store = PlanStore()
        store.add([_item(action="takeout", record_id=1, position=5)])
        store.add([_item(action="thaw", record_id=2, position=10)])
        removed = store.remove_by_key("takeout", 1, 5)
        self.assertEqual(1, removed)
        self.assertEqual(1, store.count())
        self.assertEqual("thaw", store.list_items()[0]["action"])

    def test_remove_by_key_not_found(self):
        store = PlanStore()
        store.add([_item()])
        self.assertEqual(0, store.remove_by_key("nonexistent", 99, 99))
        self.assertEqual(1, store.count())


class TestPlanStoreClearReplace(unittest.TestCase):

    def test_clear(self):
        store = PlanStore()
        store.add([_item(record_id=1), _item(record_id=2)])
        cleared = store.clear()
        self.assertEqual(2, len(cleared))
        self.assertEqual(0, store.count())

    def test_clear_empty(self):
        store = PlanStore()
        cleared = store.clear()
        self.assertEqual([], cleared)

    def test_replace_all(self):
        store = PlanStore()
        store.add([_item(record_id=1)])
        store.replace_all([_item(record_id=10), _item(record_id=20)])
        self.assertEqual(2, store.count())
        ids = [it["record_id"] for it in store.list_items()]
        self.assertEqual([10, 20], ids)

    def test_has_rollback(self):
        store = PlanStore()
        self.assertFalse(store.has_rollback())
        store.add([_item(action="rollback", record_id=None)])
        self.assertTrue(store.has_rollback())


class TestPlanStoreCallback(unittest.TestCase):

    def test_on_change_fires(self):
        calls = []
        store = PlanStore(on_change=lambda: calls.append(1))
        store.add([_item()])
        store.remove_by_index(0)
        store.add([_item()])
        store.clear()
        self.assertEqual(4, len(calls))

    def test_no_callback_on_empty_clear(self):
        calls = []
        store = PlanStore(on_change=lambda: calls.append(1))
        store.clear()
        self.assertEqual(0, len(calls))

    def test_no_callback_on_noop_remove(self):
        calls = []
        store = PlanStore(on_change=lambda: calls.append(1))
        store.remove_by_index(0)
        store.remove_by_indices([0, 1])
        store.remove_by_key("x", 0, 0)
        self.assertEqual(0, len(calls))


class TestPlanStoreItemKey(unittest.TestCase):

    def test_item_key(self):
        item = _item(action="move", record_id=3, position=7)
        self.assertEqual(("move", 3, 7), PlanStore.item_key(item))

    def test_item_key_missing_fields(self):
        self.assertEqual((None, None, None), PlanStore.item_key({}))


class TestPlanStoreThreadSafety(unittest.TestCase):

    def test_concurrent_add_remove(self):
        store = PlanStore()
        errors = []

        def adder():
            try:
                for i in range(100):
                    store.add([_item(record_id=i)], deduplicate=False)
            except Exception as e:
                errors.append(e)

        def remover():
            try:
                for _ in range(100):
                    store.remove_by_index(0)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=adder)
        t2 = threading.Thread(target=remover)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual([], errors)
        # Final count should be >= 0 (exact value depends on scheduling)
        self.assertGreaterEqual(store.count(), 0)


if __name__ == "__main__":
    unittest.main()
