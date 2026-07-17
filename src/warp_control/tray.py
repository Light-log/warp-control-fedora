"""Select the best available system-tray implementation."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Union

from warp_control.app_indicator import AppIndicatorFallback, NativeContextMenu
from warp_control.status_notifier import GioSessionBus, StatusNotifierItem


@dataclass(frozen=True)
class TrayActions:
    toggle_panel: Callable[[], None]
    refresh: Callable[[], None]
    quit: Callable[[], None]


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
        self._last_icon: Optional[Path] = None

    @property
    def active_backend(self) -> Optional[Any]:
        return self._active

    @classmethod
    def create_default(cls, actions: TrayActions) -> "TrayManager":
        try:
            bus = GioSessionBus.connect()
        except Exception:
            bus = None

        native_menu = NativeContextMenu.create_default(actions)

        def notifier_factory(icon_path: Path):
            if bus is None or native_menu is None:
                return _UnavailableBackend()
            return StatusNotifierItem(
                bus,
                actions.toggle_panel,
                native_menu.show,
                icon_path,
            )

        return cls(
            notifier_factory,
            lambda: AppIndicatorFallback.create_default(actions),
        )

    def start(self, icon_path: Union[Path, str]) -> bool:
        path = Path(icon_path)
        self._last_icon = path
        self._closed = False
        if self._active is not None:
            return self.update_icon(path)
        try:
            self._notifier = self._notifier_factory(path)
            set_callback = getattr(
                self._notifier, "set_unavailable_callback", None
            )
            if set_callback is not None:
                set_callback(self._notifier_unavailable)
            if self._notifier.start():
                self._active = self._notifier
                return True
        except Exception:
            pass
        self._safe_close(self._notifier)
        self._notifier = None
        return self._start_fallback(path)

    def update_icon(self, icon_path: Union[Path, str]) -> bool:
        path = Path(icon_path)
        self._last_icon = path
        if self._active is None:
            return False
        try:
            result = self._active.update_icon(path)
            if result is not False:
                return True
        except Exception:
            pass
        failed = self._active
        self._safe_close(failed)
        self._active = None
        if failed is self._notifier:
            self._notifier = None
            return self._start_fallback(path)
        return False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._active is not None and self._active is not self._notifier:
            self._safe_close(self._active)
        if self._notifier is not None:
            self._safe_close(self._notifier)
        self._active = None
        self._notifier = None

    def _notifier_unavailable(self) -> None:
        failed, self._notifier = self._notifier, None
        if self._active is failed:
            self._active = None
        if self._last_icon is not None and self._active is None:
            self._start_fallback(self._last_icon)

    def _start_fallback(self, path: Path) -> bool:
        try:
            fallback = self._fallback_factory()
            if fallback is None or not fallback.start(path):
                self._safe_close(fallback)
                return False
        except Exception:
            self._safe_close(locals().get("fallback"))
            return False
        self._active = fallback
        return True

    @staticmethod
    def _safe_close(backend: Optional[Any]) -> None:
        if backend is None:
            return
        try:
            backend.close()
        except Exception:
            pass


class _UnavailableBackend:
    def start(self) -> bool:
        return False

    def close(self) -> None:
        pass
