"""Unit tests for application event bus dispatch behavior."""

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_gui.application import EventBus


@dataclass
class _BaseEvent:
    text: str


@dataclass
class _ChildEvent(_BaseEvent):
    level: str = "info"


class EventBusDispatchTests(unittest.TestCase):
    def test_publish_dispatches_to_matching_handlers(self):
        bus = EventBus()
        calls = []

        bus.subscribe(_BaseEvent, lambda event: calls.append(("base", event.text)))
        bus.subscribe(_ChildEvent, lambda event: calls.append(("child", event.level)))

        errors = bus.publish(_ChildEvent(text="ok", level="warning"))

        self.assertEqual([], errors)
        self.assertEqual([("base", "ok"), ("child", "warning")], calls)

    def test_publish_isolates_handler_failures(self):
        bus = EventBus()
        calls = []

        def _bad_handler(_event):
            raise RuntimeError("boom")

        bus.subscribe(_BaseEvent, _bad_handler)
        bus.subscribe(_BaseEvent, lambda event: calls.append(event.text))

        errors = bus.publish(_BaseEvent(text="safe"))

        self.assertEqual(["safe"], calls)
        self.assertEqual(1, len(errors))
        self.assertIn("boom", str(errors[0]))

    def test_unsubscribe_removes_handler(self):
        bus = EventBus()
        calls = []

        unsubscribe = bus.subscribe(_BaseEvent, lambda event: calls.append(event.text))
        unsubscribe()
        errors = bus.publish(_BaseEvent(text="noop"))

        self.assertEqual([], errors)
        self.assertEqual([], calls)


if __name__ == "__main__":
    unittest.main()

