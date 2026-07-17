"""Application, WARP mode, protocol, and advanced settings."""

# ruff: noqa: E402 -- gi.require_version must precede repository imports.

from typing import Iterable, Optional, Tuple

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from warp_control.config import Config
from warp_control.models import WarpCapabilities
from warp_control.ui.presenters import (
    CONFIG_CONTENT_HEIGHT,
    MODE_LABELS,
    UIActions,
    preferred_supported_value,
)


VIEWPORT_HEIGHT = CONFIG_CONTENT_HEIGHT
KNOWN_MODES = ("warp", "warp+doh", "warp+dot", "doh", "dot", "tunnel_only", "proxy")
KNOWN_PROTOCOLS = ("MASQUE", "WireGuard")


class SettingsPage(Gtk.ScrolledWindow):
    def __init__(self, config: Config, actions: UIActions) -> None:
        super().__init__()
        self.actions = actions
        self._updating = False
        self.available_modes: Tuple[str, ...] = KNOWN_MODES
        self.available_protocols: Tuple[str, ...] = KNOWN_PROTOCOLS
        self.current_mode: Optional[str] = None
        self.current_protocol: Optional[str] = None
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_size_request(-1, VIEWPORT_HEIGHT)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_border_width(18)
        self.add(content)

        self.autostart_switch = self._switch_row(
            content, "Iniciar con la sesión", actions.on_autostart_changed
        )
        self.auto_update_switch = self._switch_row(
            content, "Actualizar automáticamente", actions.on_auto_update_changed
        )

        interval_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        interval_label = Gtk.Label(label="Intervalo de actualización (segundos)")
        interval_label.set_xalign(0)
        interval_label.set_hexpand(True)
        interval_row.pack_start(interval_label, True, True, 0)
        self.interval_spin = Gtk.SpinButton.new_with_range(1, 3600, 1)
        self.interval_spin.connect(
            "value-changed",
            lambda spin: None
            if self._updating
            else actions.on_interval_changed(spin.get_value_as_int()),
        )
        interval_row.pack_start(self.interval_spin, False, False, 0)
        content.pack_start(interval_row, False, False, 0)

        self.mode_combo = self._combo_row(content, "Modo")
        self.mode_combo.connect("changed", self._on_mode_changed)
        self.protocol_combo = self._combo_row(content, "Protocolo")
        self.protocol_combo.connect("changed", self._on_protocol_changed)

        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        content.pack_start(separator, False, False, 4)
        tools_label = Gtk.Label(label="Herramientas avanzadas")
        tools_label.set_xalign(0)
        content.pack_start(tools_label, False, False, 0)
        self.restart_button = self._tool_button(
            content, "Reiniciar warp-svc", actions.on_restart_service
        )
        self.test_button = self._tool_button(
            content, "Probar conectividad", actions.on_test_connection
        )
        self.log_button = self._tool_button(content, "Abrir registro", actions.on_open_log)

        self.set_capabilities_values(KNOWN_MODES, KNOWN_PROTOCOLS)
        self.apply_config(config)

    def _switch_row(self, parent: Gtk.Box, label: str, callback) -> Gtk.Switch:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        text = Gtk.Label(label=label)
        text.set_xalign(0)
        text.set_hexpand(True)
        row.pack_start(text, True, True, 0)
        switch = Gtk.Switch()
        switch.connect(
            "notify::active",
            lambda widget, _parameter: None
            if self._updating
            else callback(widget.get_active()),
        )
        row.pack_start(switch, False, False, 0)
        parent.pack_start(row, False, False, 0)
        return switch

    @staticmethod
    def _combo_row(parent: Gtk.Box, label: str) -> Gtk.ComboBoxText:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        text = Gtk.Label(label=label)
        text.set_xalign(0)
        text.set_hexpand(True)
        row.pack_start(text, True, True, 0)
        combo = Gtk.ComboBoxText()
        row.pack_start(combo, False, False, 0)
        parent.pack_start(row, False, False, 0)
        return combo

    @staticmethod
    def _tool_button(parent: Gtk.Box, label: str, callback) -> Gtk.Button:
        button = Gtk.Button(label=label)
        button.connect("clicked", lambda _button: callback())
        parent.pack_start(button, False, True, 0)
        return button

    @staticmethod
    def _populate(combo: Gtk.ComboBoxText, values: Iterable[str], labels=None) -> None:
        combo.remove_all()
        for value in values:
            combo.append(value, labels.get(value, value) if labels else value)
        combo.set_active(0 if combo.get_model() and len(combo.get_model()) else -1)

    def set_capabilities_values(
        self,
        modes: Iterable[str],
        protocols: Iterable[str],
        current_mode: Optional[str] = None,
        current_protocol: Optional[str] = None,
    ) -> None:
        if current_mode is None:
            current_mode = self.current_mode or self.mode_combo.get_active_id()
        if current_protocol is None:
            current_protocol = (
                self.current_protocol or self.protocol_combo.get_active_id()
            )
        self.available_modes = tuple(value for value in KNOWN_MODES if value in modes)
        self.available_protocols = tuple(
            value for value in KNOWN_PROTOCOLS if value in protocols
        )
        self._updating = True
        self._populate(self.mode_combo, self.available_modes, MODE_LABELS)
        self._populate(self.protocol_combo, self.available_protocols)
        self.current_mode = preferred_supported_value(
            current_mode, self.available_modes
        )
        self.current_protocol = preferred_supported_value(
            current_protocol, self.available_protocols
        )
        self.mode_combo.set_active_id(self.current_mode)
        self.protocol_combo.set_active_id(self.current_protocol)
        self.mode_combo.set_sensitive(bool(self.available_modes))
        self.protocol_combo.set_sensitive(bool(self.available_protocols))
        self._updating = False

    def set_capabilities(
        self,
        capabilities: WarpCapabilities,
        current_mode: Optional[str] = None,
        current_protocol: Optional[str] = None,
    ) -> None:
        if not capabilities.ok:
            if current_mode is not None or current_protocol is not None:
                self.apply_current_settings(current_mode, current_protocol)
            return
        self.set_capabilities_values(
            capabilities.modes,
            capabilities.protocols,
            current_mode,
            current_protocol,
        )

    def apply_current_settings(
        self, mode: Optional[str], protocol: Optional[str]
    ) -> None:
        self._updating = True
        if mode is not None:
            self.current_mode = mode
            self.mode_combo.set_active_id(mode)
        if protocol is not None:
            self.current_protocol = protocol
            self.protocol_combo.set_active_id(protocol)
        self._updating = False

    def apply_config(self, config: Config) -> None:
        self._updating = True
        self.autostart_switch.set_active(config.autostart_enabled)
        self.auto_update_switch.set_active(config.auto_update_enabled)
        self.interval_spin.set_value(config.update_interval_seconds)
        self.interval_spin.set_sensitive(config.auto_update_enabled)
        self._updating = False

    def _on_mode_changed(self, combo: Gtk.ComboBoxText) -> None:
        value = combo.get_active_id()
        if not self._updating and value is not None:
            self.current_mode = value
            self.actions.on_mode_changed(value)

    def _on_protocol_changed(self, combo: Gtk.ComboBoxText) -> None:
        value = combo.get_active_id()
        if not self._updating and value is not None:
            self.current_protocol = value
            self.actions.on_protocol_changed(value)
