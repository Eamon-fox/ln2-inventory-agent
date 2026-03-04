"""In-process event bus for application-level events."""

from collections import defaultdict
from typing import Callable, DefaultDict, List, Type


class EventBus:
    """Minimal synchronous event bus with failure isolation."""

    def __init__(self):
        self._handlers: DefaultDict[type, List[Callable]] = defaultdict(list)

    def subscribe(self, event_type: Type, handler: Callable):
        """Subscribe handler to event_type and return an unsubscribe callable."""
        self._handlers[event_type].append(handler)

        def _unsubscribe():
            handlers = self._handlers.get(event_type, [])
            try:
                handlers.remove(handler)
            except ValueError:
                return
            if not handlers:
                self._handlers.pop(event_type, None)

        return _unsubscribe

    def publish(self, event) -> List[Exception]:
        """Publish event and return non-fatal handler exceptions."""
        errors: List[Exception] = []
        for event_type, handlers in list(self._handlers.items()):
            if not isinstance(event, event_type):
                continue
            for handler in list(handlers):
                try:
                    handler(event)
                except Exception as exc:  # pragma: no cover - surfaced via return value
                    errors.append(exc)
        return errors

