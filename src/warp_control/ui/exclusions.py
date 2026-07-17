"""Exclusion editor with callback-only mutations."""

# ruff: noqa: E402 -- gi.require_version must precede repository imports.

from pathlib import Path
from typing import Iterable, Optional, Tuple, Union

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from warp_control.ui.assets import runtime_asset_path
from warp_control.ui.presenters import CONFIG_CONTENT_HEIGHT, UIActions


VIEWPORT_HEIGHT = CONFIG_CONTENT_HEIGHT
class ExclusionsPage(Gtk.ScrolledWindow):
    def __init__(
        self,
        actions: UIActions,
        delete_icon_path: Optional[Union[Path, str]] = None,
    ) -> None:
        super().__init__()
        self.actions = actions
        self.delete_icon_path = (
            Path(delete_icon_path)
            if delete_icon_path is not None
            else runtime_asset_path("edit-delete.svg")
        )
        self.hosts: Tuple[str, ...] = ()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_size_request(-1, VIEWPORT_HEIGHT)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_border_width(18)
        self.add(content)

        explanation = Gtk.Label(
            label="Añade dominios que WARP debe excluir de la conexión segura."
        )
        explanation.set_line_wrap(True)
        explanation.set_xalign(0)
        explanation.get_style_context().add_class("muted")
        content.pack_start(explanation, False, False, 0)

        add_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.url_entry = Gtk.Entry()
        self.url_entry.set_placeholder_text("ejemplo.com o https://ejemplo.com")
        self.url_entry.set_hexpand(True)
        add_row.pack_start(self.url_entry, True, True, 0)
        self.add_button = Gtk.Button(label="Añadir")
        self.add_button.get_style_context().add_class("accent-action")
        self.add_button.connect("clicked", self._on_add_clicked)
        add_row.pack_start(self.add_button, False, False, 0)
        content.pack_start(add_row, False, False, 0)

        self.subdomains_check = Gtk.CheckButton(label="Incluir subdominios")
        content.pack_start(self.subdomains_check, False, False, 0)

        self.rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content.pack_start(self.rows_box, False, False, 0)

    def _on_add_clicked(self, _button: Gtk.Button) -> None:
        value = self.url_entry.get_text().strip()
        if value:
            self.actions.on_add_host(value, self.subdomains_check.get_active())

    def _on_remove_clicked(self, _button: Gtk.Button, host: str) -> None:
        self.actions.on_remove_host(host)

    def set_hosts(self, hosts: Iterable[str]) -> None:
        self.hosts = tuple(hosts)
        for child in self.rows_box.get_children():
            self.rows_box.remove(child)
        for host in self.hosts:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            label = Gtk.Label(label=host)
            label.set_xalign(0)
            label.set_hexpand(True)
            row.pack_start(label, True, True, 0)
            remove = Gtk.Button()
            remove.set_tooltip_text(f"Eliminar {host}")
            remove.set_relief(Gtk.ReliefStyle.NONE)
            remove.add(Gtk.Image.new_from_file(str(self.delete_icon_path)))
            remove.connect("clicked", self._on_remove_clicked, host)
            row.pack_start(remove, False, False, 0)
            self.rows_box.pack_start(row, False, False, 0)
        self.rows_box.show_all()
