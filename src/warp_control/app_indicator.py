"""Ayatana AppIndicator compatibility fallback."""

from pathlib import Path
from typing import Any, Optional, Union


def _build_menu(gtk: Any, actions: Any):
    menu = gtk.Menu()
    for label, callback in (
        ("Abrir panel", actions.toggle_panel),
        ("Actualizar", actions.refresh),
        ("Salir", actions.quit),
    ):
        item = gtk.MenuItem(label=label)
        item.connect("activate", lambda _item, action=callback: action())
        menu.append(item)
    menu.show_all()
    return menu


class NativeContextMenu:
    """Concrete GTK menu used by the StatusNotifierItem ContextMenu method."""

    def __init__(self, gtk: Any, actions: Any) -> None:
        self._gtk = gtk
        self.widget = _build_menu(gtk, actions)

    @classmethod
    def create_default(cls, actions: Any) -> Optional["NativeContextMenu"]:
        try:
            import gi

            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk
        except (ImportError, ValueError):
            return None
        return cls(Gtk, actions)

    def show(self, _x: int, _y: int) -> None:
        if hasattr(self.widget, "popup_at_pointer"):
            self.widget.popup_at_pointer(None)
            return
        event_time = self._gtk.get_current_event_time()
        self.widget.popup(None, None, None, None, 0, event_time)


class AppIndicatorFallback:
    """Native three-item fallback menu for desktops without an SNI watcher."""

    def __init__(self, gtk: Any, indicator_module: Any, actions: Any) -> None:
        self._gtk = gtk
        self._module = indicator_module
        self._actions = actions
        self._indicator = None
        self._menu = None

    @classmethod
    def create_default(cls, actions: Any) -> Optional["AppIndicatorFallback"]:
        try:
            import gi

            gi.require_version("Gtk", "3.0")
            try:
                gi.require_version("AyatanaAppIndicator3", "0.1")
                from gi.repository import AyatanaAppIndicator3 as Indicator
            except (ImportError, ValueError):
                gi.require_version("AppIndicator3", "0.1")
                from gi.repository import AppIndicator3 as Indicator
            from gi.repository import Gtk
        except (ImportError, ValueError):
            return None
        return cls(Gtk, Indicator, actions)

    def start(self, icon_path: Union[Path, str]) -> bool:
        if self._indicator is not None:
            return True
        try:
            module = self._module
            self._indicator = module.Indicator.new(
                "warp-control",
                "warp-control",
                module.IndicatorCategory.APPLICATION_STATUS,
            )
            self._menu = _build_menu(self._gtk, self._actions)
            self._indicator.set_menu(self._menu)
            if not self.update_icon(icon_path):
                raise RuntimeError("indicator rejected icon")
            self._indicator.set_status(module.IndicatorStatus.ACTIVE)
            return True
        except Exception:
            self.close()
            return False

    def update_icon(self, icon_path: Union[Path, str]) -> bool:
        path = Path(icon_path).expanduser().resolve(strict=False)
        if self._indicator is None:
            return False
        try:
            self._indicator.set_icon_theme_path(str(path.parent))
            self._indicator.set_icon_full(path.stem, "Estado de Cloudflare WARP")
        except Exception:
            return False
        return True

    def close(self) -> None:
        if self._indicator is not None:
            passive = getattr(self._module.IndicatorStatus, "PASSIVE", None)
            if passive is not None:
                try:
                    self._indicator.set_status(passive)
                except Exception:
                    pass
        self._indicator = None
        self._menu = None
