"""In-process event bus for application-level events."""

from collections import defaultdict
from typing import Callable, DefaultDict, List, Type

from lib.diagnostics import event_bus_trace_enabled, log_event, span


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
        trace_enabled = event_bus_trace_enabled()
        event_name = type(event).__name__
        matching = [
            (event_type, list(handlers))
            for event_type, handlers in list(self._handlers.items())
            if isinstance(event, event_type)
        ]
        handler_count = sum(len(handlers) for _event_type, handlers in matching)

        publish_context = (
            span(
                "event_bus.publish",
                event_type=event_name,
                subscriber_count=handler_count,
            )
            if trace_enabled
            else None
        )
        if publish_context is None:
            for _event_type, handlers in matching:
                for handler in handlers:
                    try:
                        handler(event)
                    except Exception as exc:  # pragma: no cover - surfaced via return value
                        errors.append(exc)
            return errors

        with publish_context:
            for event_type, handlers in matching:
                for handler in handlers:
                    handler_name = getattr(handler, "__qualname__", None) or getattr(handler, "__name__", None)
                    try:
                        with span(
                            "event_bus.handler",
                            event_type=event_name,
                            subscribed_type=getattr(event_type, "__name__", str(event_type)),
                            handler=str(handler_name or type(handler).__name__),
                        ):
                            handler(event)
                    except Exception as exc:  # pragma: no cover - surfaced via return value
                        errors.append(exc)
                        log_event(
                            "event_bus.handler_error",
                            event_type=event_name,
                            subscribed_type=getattr(event_type, "__name__", str(event_type)),
                            handler=str(handler_name or type(handler).__name__),
                            exception_type=type(exc).__name__,
                            exception=str(exc),
                        )
        return errors

