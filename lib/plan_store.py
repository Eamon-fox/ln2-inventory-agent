"""Thread-safe plan item staging store.

Shared by GUI (OperationsPanel) and agent (AgentToolRunner).
No Qt imports — framework-agnostic.
"""

import threading
from copy import deepcopy


class PlanStore:
    """Holds staged plan items with thread-safe access.

    Parameters
    ----------
    on_change : callable, optional
        Called (with no args) after every mutation.  The GUI layer
        connects this to a Qt signal for UI refresh.
    """

    def __init__(self, on_change=None):
        self._items = []
        self._lock = threading.Lock()
        self._on_change = on_change

    def _notify(self):
        cb = self._on_change
        if cb:
            cb()

    @staticmethod
    def item_key(item):
        """Dedup key: (action, record_id, position)."""
        return (item.get("action"), item.get("record_id"), item.get("position"))

    # ---- Read ----

    def list_items(self):
        """Return a deep-copied snapshot of all staged items."""
        with self._lock:
            return deepcopy(self._items)

    def count(self):
        with self._lock:
            return len(self._items)

    def has_rollback(self):
        with self._lock:
            return any(
                str(it.get("action") or "").lower() == "rollback"
                for it in self._items
            )

    # ---- Write ----

    def add(self, items, deduplicate=True):
        """Add items, optionally replacing duplicates by key.

        Returns the number of items added/replaced.
        """
        with self._lock:
            added = 0
            for item in items:
                if deduplicate:
                    key = self.item_key(item)
                    replaced = False
                    for i, existing in enumerate(self._items):
                        if self.item_key(existing) == key:
                            self._items[i] = item
                            replaced = True
                            break
                    if not replaced:
                        self._items.append(item)
                else:
                    self._items.append(item)
                added += 1
        self._notify()
        return added

    def remove_by_index(self, index):
        """Remove item at *index*. Returns the removed item or ``None``."""
        with self._lock:
            if 0 <= index < len(self._items):
                removed = self._items.pop(index)
            else:
                return None
        self._notify()
        return removed

    def remove_by_indices(self, indices):
        """Remove items at multiple indices. Returns count removed."""
        with self._lock:
            count = 0
            for idx in sorted(set(indices), reverse=True):
                if 0 <= idx < len(self._items):
                    self._items.pop(idx)
                    count += 1
        if count:
            self._notify()
        return count

    def remove_by_key(self, action, record_id, position):
        """Remove items matching the (action, record_id, position) key.

        Returns count removed.
        """
        key = (action, record_id, position)
        with self._lock:
            before = len(self._items)
            self._items = [it for it in self._items if self.item_key(it) != key]
            count = before - len(self._items)
        if count:
            self._notify()
        return count

    def clear(self):
        """Clear all items. Returns the list of cleared items."""
        with self._lock:
            cleared = list(self._items)
            self._items.clear()
        if cleared:
            self._notify()
        return cleared

    def replace_all(self, items):
        """Replace entire list (e.g. after plan execution)."""
        with self._lock:
            self._items = list(items)
        self._notify()
