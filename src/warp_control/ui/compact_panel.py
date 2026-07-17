"""Compact status and connection controls."""

# ruff: noqa: E402 -- gi.require_version must precede repository imports.

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from warp_control.models import WarpState
from warp_control.ui.presenters import UIActions, present_state


class CompactPanel(Gtk.Box):
    def __init__(self, actions: UIActions, on_modify) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.set_border_width(24)
        self.get_style_context().add_class("surface")

        self.cloudflare_icon = Gtk.Image.new_from_icon_name(
            "cloudflare-warp", Gtk.IconSize.DIALOG
        )
        self.cloudflare_icon.set_widget_name("cloudflare-icon")
        self.pack_start(self.cloudflare_icon, False, False, 0)

        self.state_label = Gtk.Label()
        self.state_label.set_widget_name("compact-state-label")
        self.state_label.get_style_context().add_class("state-badge")
        self.pack_start(self.state_label, False, False, 0)

        self.action_button = Gtk.Button()
        self.action_button.get_style_context().add_class("state-action")
        self.action_button.connect("clicked", lambda _button: actions.on_toggle_connection())
        self.pack_start(self.action_button, False, True, 0)

        self.modify_button = Gtk.Button(label="Modificar")
        self.modify_button.set_hexpand(True)
        self.modify_button.get_style_context().add_class("accent-action")
        self.modify_button.connect("clicked", lambda _button: on_modify())
        self.pack_start(self.modify_button, False, True, 0)

        self.apply_state(WarpState.UNKNOWN)

    def apply_state(self, state: WarpState) -> None:
        presentation = present_state(state)
        self.state_label.set_text(presentation.status_label)
        self.action_button.set_label(presentation.action_label)
        self.action_button.set_sensitive(presentation.action_sensitive)
