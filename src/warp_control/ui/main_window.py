"""The application's single window and its compact/configuration stack."""

# ruff: noqa: E402 -- gi.require_version must precede repository imports.

from pathlib import Path
from typing import Iterable, Optional, Union

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk

from warp_control.config import Config
from warp_control.models import WarpCapabilities, WarpState
from warp_control.ui.appearance import AppearancePage
from warp_control.ui.compact_panel import CompactPanel
from warp_control.ui.exclusions import ExclusionsPage
from warp_control.ui.presenters import CONFIG_WIDTH, UIActions, present_state
from warp_control.ui.settings import SettingsPage
from warp_control.ui.theme import ScreenProviderBinding, build_css


class MainWindow(Gtk.Window):
    def __init__(self, config: Config, actions: UIActions) -> None:
        super().__init__(title="WARP Control")
        self.config = config
        self.state = WarpState.UNKNOWN
        self.set_default_size(CONFIG_WIDTH, 570)
        self.set_resizable(False)
        self.connect("delete-event", self._on_delete_event)
        self._css_provider = Gtk.CssProvider()
        self._provider_binding = ScreenProviderBinding(
            self._css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.add(self.stack)

        self.compact_panel = CompactPanel(actions, self.show_configuration)
        self.stack.add_named(self.compact_panel, "compact")

        self.configuration = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.configuration.get_style_context().add_class("app-shell")
        self.stack.add_named(self.configuration, "configuration")

        self._build_header()
        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(False)
        self.exclusions = ExclusionsPage(actions)
        self.appearance = AppearancePage(config, actions)
        self.settings = SettingsPage(config, actions)
        for page, title in (
            (self.exclusions, "Exclusiones"),
            (self.appearance, "Apariencia"),
            (self.settings, "Ajustes"),
        ):
            self.notebook.append_page(page, Gtk.Label(label=title))
        self.configuration.pack_start(self.notebook, True, True, 0)

        self.show_compact()
        self.apply_config(config)
        self.apply_state(WarpState.UNKNOWN)

    def _build_header(self) -> None:
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        header.set_border_width(16)
        header.get_style_context().add_class("integrated-header")

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        back = Gtk.Button(label="Panel")
        back.set_relief(Gtk.ReliefStyle.NONE)
        back.connect("clicked", lambda _button: self.show_compact())
        top.pack_start(back, False, False, 0)
        title = Gtk.Label(label="WARP Control")
        title.set_xalign(0)
        title.set_hexpand(True)
        top.pack_start(title, True, True, 0)
        header.pack_start(top, False, False, 0)

        self.hero_state_label = Gtk.Label()
        self.hero_state_label.set_xalign(0)
        self.hero_state_label.get_style_context().add_class("state-badge")
        header.pack_start(self.hero_state_label, False, False, 0)
        self.configuration.pack_start(header, False, False, 0)

    def _on_delete_event(self, _window: Gtk.Window, _event: object) -> bool:
        self.hide()
        return True

    def show_compact(self) -> None:
        self.stack.set_visible_child_name("compact")

    def show_configuration(self) -> None:
        self.stack.set_visible_child_name("configuration")

    def show_settings(self) -> None:
        self.show_configuration()
        self.notebook.set_current_page(2)

    def apply_state(
        self, state: WarpState, icon_path: Optional[Union[Path, str]] = None
    ) -> None:
        self.state = state
        presentation = present_state(state)
        self.compact_panel.apply_state(state)
        if icon_path is not None:
            self.set_state_icon(icon_path)
        self.hero_state_label.set_text(presentation.status_label)
        self.apply_theme(self.config)

    def apply_config(self, config: Config) -> None:
        self.config = config
        self.appearance.apply_config(config)
        self.settings.apply_config(config)
        self.apply_theme(config)

    def apply_theme(self, config: Config) -> None:
        self._css_provider.load_from_data(
            build_css(config, self.state).encode("utf-8")
        )
        screen = Gdk.Screen.get_default()
        self._provider_binding.install(
            screen,
            Gtk.StyleContext.add_provider_for_screen,
            Gtk.StyleContext.remove_provider_for_screen,
        )

    def set_state_icon(self, path: Union[Path, str]) -> None:
        self.compact_panel.set_icon(path)

    def set_hosts(self, hosts: Iterable[str]) -> None:
        self.exclusions.set_hosts(hosts)

    def set_capabilities(self, capabilities: WarpCapabilities) -> None:
        self.settings.set_capabilities(capabilities)
