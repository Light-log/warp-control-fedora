"""Theme and color controls without persistence side effects."""

# ruff: noqa: E402 -- gi.require_version must precede repository imports.

from typing import Dict

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk

from warp_control.config import Config
from warp_control.ui.presenters import CONFIG_CONTENT_HEIGHT, UIActions


VIEWPORT_HEIGHT = CONFIG_CONTENT_HEIGHT
STATE_LABELS = {
    "connected": "Conectado",
    "connecting": "Conectando",
    "disconnected": "Desconectado",
    "error": "Error",
}


def _rgba_to_hex(rgba: Gdk.RGBA) -> str:
    values = (rgba.red, rgba.green, rgba.blue)
    return "#" + "".join(f"{round(value * 255):02X}" for value in values)


class AppearancePage(Gtk.ScrolledWindow):
    def __init__(self, config: Config, actions: UIActions) -> None:
        super().__init__()
        self.actions = actions
        self._updating = False
        self.color_buttons: Dict[str, Dict[str, Gtk.ColorButton]] = {}
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_size_request(-1, VIEWPORT_HEIGHT)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_border_width(18)
        self.add(content)

        theme_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label = Gtk.Label(label="Tema oscuro")
        label.set_xalign(0)
        label.set_hexpand(True)
        theme_row.pack_start(label, True, True, 0)
        self.theme_switch = Gtk.Switch()
        self.theme_switch.connect("notify::active", self._on_theme_changed)
        theme_row.pack_start(self.theme_switch, False, False, 0)
        content.pack_start(theme_row, False, False, 0)

        grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        grid.attach(Gtk.Label(label="Estado"), 0, 0, 1, 1)
        grid.attach(Gtk.Label(label="Principal"), 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Secundario"), 2, 0, 1, 1)
        for row_index, (state, state_label) in enumerate(STATE_LABELS.items(), start=1):
            state_name = Gtk.Label(label=state_label)
            state_name.set_xalign(0)
            grid.attach(state_name, 0, row_index, 1, 1)
            self.color_buttons[state] = {}
            for column, role in ((1, "primary"), (2, "secondary")):
                button = Gtk.ColorButton()
                button.set_title(f"{state_label}: {role}")
                button.connect("color-set", self._on_state_color_changed, state, role)
                self.color_buttons[state][role] = button
                grid.attach(button, column, row_index, 1, 1)
        content.pack_start(grid, False, False, 0)

        accent_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        accent_label = Gtk.Label(label="Color de acento")
        accent_label.set_xalign(0)
        accent_label.set_hexpand(True)
        accent_row.pack_start(accent_label, True, True, 0)
        self.accent_button = Gtk.ColorButton()
        self.accent_button.set_title("Color de acento")
        self.accent_button.connect("color-set", self._on_accent_changed)
        accent_row.pack_start(self.accent_button, False, False, 0)
        content.pack_start(accent_row, False, False, 0)

        reset = Gtk.Button(label="Restablecer valores predeterminados")
        reset.connect("clicked", lambda _button: actions.on_reset_appearance())
        content.pack_start(reset, False, True, 0)
        self.apply_config(config)

    @staticmethod
    def _set_color(button: Gtk.ColorButton, value: str) -> None:
        rgba = Gdk.RGBA()
        if rgba.parse(value):
            button.set_rgba(rgba)

    def apply_config(self, config: Config) -> None:
        self._updating = True
        self.theme_switch.set_active(config.theme == "dark")
        for state, buttons in self.color_buttons.items():
            for role, button in buttons.items():
                self._set_color(button, config.colors[state][role])
        self._set_color(self.accent_button, config.accent)
        self._updating = False

    def _on_theme_changed(self, switch: Gtk.Switch, _parameter: object) -> None:
        if not self._updating:
            self.actions.on_theme_changed("dark" if switch.get_active() else "light")

    def _on_state_color_changed(
        self, button: Gtk.ColorButton, state: str, role: str
    ) -> None:
        if not self._updating:
            self.actions.on_color_changed(state, role, _rgba_to_hex(button.get_rgba()))

    def _on_accent_changed(self, button: Gtk.ColorButton) -> None:
        if not self._updating:
            self.actions.on_accent_changed(_rgba_to_hex(button.get_rgba()))
