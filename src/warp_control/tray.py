"""Select the best available system-tray implementation."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Union

from warp_control.app_indicator import AppIndicatorFallback
from warp_control.status_notifier import GioSessionBus, StatusNotifierItem


@dataclass(frozen=True)
class TrayActions:
    toggle_panel: Callable[[], None]
    refresh: Callable[[], None]
    quit: Callable[[], None]
    show_context_menu: Callable[[int, int], None]


class TrayManager:
    """Own exactly one active tray backend and clean it up idempotently."""

    def __init__(
        self,
        notifier_factory: Callable[[Path], Any],
        fallback_factory: Callable[[], Optional[Any]],
    ) -> None:
        self._notifier_factory = notifier_factory
        self._fallback_factory = fallback_factory
        self._notifier = None
        self._active = None
        self._closed = False

    @classmethod
    def create_default(cls, actions: TrayActions) -> "TrayManager":
        try:
            bus = GioSessionBus.connect()
        except (ImportError, RuntimeError):
            bus = None

        def notifier_factory(icon_path: Path):
            if bus is None:
                return _UnavailableBackend()
            return StatusNotifierItem(
                bus,
                actions.toggle_panel,
                actions.show_context_menu,
                icon_path,
            )

        return cls(
            notifier_factory,
            lambda: AppIndicatorFallback.create_default(actions),
        )

    def start(self, icon_path: Union[Path, str]) -> bool:
        path = Path(icon_path)
        self._closed = False
        self._notifier = self._notifier_factory(path)
        if self._notifier.start():
            self._active = self._notifier
            return True
        self._notifier.close()
        self._notifier = None
        fallback = self._fallback_factory()
        if fallback is None or not fallback.start(path):
            return False
        self._active = fallback
        return True

    def update_icon(self, icon_path: Union[Path, str]) -> None:
        if self._active is not None:
            self._active.update_icon(Path(icon_path))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._active is not None and self._active is not self._notifier:
            self._active.close()
        if self._notifier is not None:
            self._notifier.close()
        self._active = None


class _UnavailableBackend:
    def start(self) -> bool:
        return False

    def close(self) -> None:
        pass
