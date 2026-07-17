"""Small GLib-aware primitives for work outside the GTK main loop."""

import threading
from typing import Any, Callable, Optional


class BackgroundTasks:
    """Run blocking callables in daemon threads and marshal results to GLib."""

    def __init__(
        self,
        idle_add: Optional[Callable[[Callable[[], bool]], Any]] = None,
        thread_factory: Callable[..., threading.Thread] = threading.Thread,
    ) -> None:
        if idle_add is None:
            from gi.repository import GLib

            idle_add = GLib.idle_add
        self._idle_add = idle_add
        self._thread_factory = thread_factory

    def submit(
        self,
        worker: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> threading.Thread:
        def deliver(callback: Callable[..., None], value: Any) -> None:
            def invoke() -> bool:
                callback(value)
                return False

            self._idle_add(invoke)

        def run() -> None:
            try:
                result = worker()
            except Exception as error:
                if on_error is not None:
                    deliver(on_error, error)
                return
            deliver(on_success, result)

        thread = self._thread_factory(
            target=run, name="warp-control-worker", daemon=True
        )
        thread.start()
        return thread


class PeriodicScheduler:
    """Own one recurring GLib timeout and cancel it idempotently."""

    def __init__(
        self,
        timeout_add_seconds: Optional[Callable[..., int]] = None,
        source_remove: Optional[Callable[[int], Any]] = None,
    ) -> None:
        if timeout_add_seconds is None or source_remove is None:
            from gi.repository import GLib

            timeout_add_seconds = timeout_add_seconds or GLib.timeout_add_seconds
            source_remove = source_remove or GLib.source_remove
        self._timeout_add_seconds = timeout_add_seconds
        self._source_remove = source_remove
        self._source_id: Optional[int] = None

    def start(self, callback: Callable[[], Any], interval: int = 5) -> None:
        if isinstance(interval, bool) or interval <= 0:
            raise ValueError("interval must be a positive integer")
        self.stop()

        def tick() -> bool:
            callback()
            return True

        self._source_id = self._timeout_add_seconds(interval, tick)

    def stop(self) -> None:
        source_id, self._source_id = self._source_id, None
        if source_id is not None:
            self._source_remove(source_id)
