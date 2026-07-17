"""Ayatana AppIndicator compatibility fallback."""

from pathlib import Path
from typing import Any, Optional, Union


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
        module = self._module
        self._indicator = module.Indicator.new(
            "warp-control",
            "warp-control",
            module.IndicatorCategory.APPLICATION_STATUS,
        )
        self._menu = self._build_menu()
        self._indicator.set_menu(self._menu)
        self.update_icon(icon_path)
        self._indicator.set_status(module.IndicatorStatus.ACTIVE)
        self._menu.show_all()
        return True

    def _build_menu(self):
        menu = self._gtk.Menu()
        for label, callback in (
            ("Abrir panel", self._actions.toggle_panel),
            ("Actualizar", self._actions.refresh),
            ("Salir", self._actions.quit),
        ):
            item = self._gtk.MenuItem(label=label)
            item.connect("activate", lambda _item, action=callback: action())
            menu.append(item)
        return menu

    def update_icon(self, icon_path: Union[Path, str]) -> None:
        path = Path(icon_path).expanduser().resolve(strict=False)
        if self._indicator is None:
            return
        self._indicator.set_icon_theme_path(str(path.parent))
        self._indicator.set_icon_full(path.stem, "Estado de Cloudflare WARP")

    def close(self) -> None:
        if self._indicator is not None:
            passive = getattr(self._module.IndicatorStatus, "PASSIVE", None)
            if passive is not None:
                self._indicator.set_status(passive)
        self._indicator = None
        self._menu = None
