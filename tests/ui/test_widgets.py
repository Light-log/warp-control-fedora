from pathlib import Path

import pytest

pytestmark = pytest.mark.ui

gi = pytest.importorskip("gi", reason="PyGObject is unavailable")
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402


_init_result = Gtk.init_check([])
_gtk_ready = _init_result[0] if isinstance(_init_result, tuple) else _init_result
if not _gtk_ready:
    pytest.skip("GTK display unavailable; widget tests require a display", allow_module_level=True)

from warp_control.config import Config  # noqa: E402
from warp_control.models import WarpCapabilities, WarpState  # noqa: E402
from warp_control.ui.appearance import VIEWPORT_HEIGHT as APPEARANCE_HEIGHT  # noqa: E402
from warp_control.ui.exclusions import VIEWPORT_HEIGHT as EXCLUSIONS_HEIGHT  # noqa: E402
from warp_control.ui.main_window import MainWindow  # noqa: E402
from warp_control.ui.presenters import CONFIG_CONTENT_HEIGHT, UIActions  # noqa: E402
from warp_control.ui.settings import VIEWPORT_HEIGHT as SETTINGS_HEIGHT  # noqa: E402


def test_main_window_uses_one_top_level_stack_and_same_window_for_modify():
    window = MainWindow(Config(), UIActions())
    assert isinstance(window, Gtk.Window)
    assert window.get_child() is window.stack
    assert window.stack.get_child_by_name("compact") is window.compact_panel
    assert window.stack.get_child_by_name("configuration") is window.configuration
    assert window.stack.get_visible_child_name() == "compact"

    window.compact_panel.modify_button.clicked()
    assert window.stack.get_visible_child_name() == "configuration"
    window.show_compact()
    assert window.stack.get_visible_child_name() == "compact"

    window.show_all()
    window.show_configuration()
    assert window.stack.get_visible_child_name() == "configuration"
    window.show_compact()
    assert window.stack.get_visible_child_name() == "compact"

    assert len([widget for widget in Gtk.Window.list_toplevels() if widget is window]) == 1
    window.destroy()


def test_state_svg_is_loaded_by_compact_panel_and_main_window(tmp_path):
    icon = tmp_path / "connected.svg"
    icon.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24">'
        '<rect width="24" height="24" fill="#16A34A"/></svg>',
        encoding="utf-8",
    )
    window = MainWindow(Config(), UIActions())
    original_provider = window._css_provider

    window.apply_state(WarpState.CONNECTED, icon)
    window.apply_config(Config(theme="light", accent="#1267D6"))

    assert window.compact_panel.cloudflare_icon.get_storage_type() == Gtk.ImageType.PIXBUF
    assert window.compact_panel.cloudflare_icon.get_pixbuf() is not None
    assert window._css_provider is original_provider
    window.destroy()


def test_configuration_has_fixed_viewport_and_three_internally_scrolled_tabs():
    window = MainWindow(Config(), UIActions())
    assert window.get_default_size()[0] == 420
    assert EXCLUSIONS_HEIGHT == APPEARANCE_HEIGHT == SETTINGS_HEIGHT == CONFIG_CONTENT_HEIGHT
    assert window.notebook.get_n_pages() == 3
    assert [window.notebook.get_tab_label_text(window.notebook.get_nth_page(index)) for index in range(3)] == [
        "Exclusiones",
        "Apariencia",
        "Ajustes",
    ]
    assert all(isinstance(window.notebook.get_nth_page(index), Gtk.ScrolledWindow) for index in range(3))
    window.destroy()


def test_public_updates_and_callbacks_cover_hosts_state_and_capabilities():
    calls = []
    window = MainWindow(
        Config(),
        UIActions(
            on_add_host=lambda host, subdomains: calls.append(("add", host, subdomains)),
            on_remove_host=lambda host: calls.append(("remove", host)),
        ),
    )
    window.apply_state(WarpState.CONNECTED)
    window.set_hosts(("example.com",))
    window.set_capabilities(
        WarpCapabilities(True, ("warp", "proxy"), ("MASQUE",), "remove", "")
    )

    assert window.compact_panel.state_label.get_text() == "Conectado"
    assert window.exclusions.hosts == ("example.com",)
    assert window.settings.available_modes == ("warp", "proxy")
    assert window.settings.available_protocols == ("MASQUE",)
    window.destroy()


def test_mode_and_protocol_state_survives_capability_probe_failure():
    window = MainWindow(Config(), UIActions())
    supported = WarpCapabilities(
        True, ("warp", "proxy"), ("MASQUE", "WireGuard"), "remove", ""
    )
    failed = WarpCapabilities(False, (), (), "remove", "probe failed")

    window.set_capabilities(supported, current_mode="proxy", current_protocol="WireGuard")
    assert window.settings.mode_combo.get_active_id() == "proxy"
    assert window.settings.protocol_combo.get_active_id() == "WireGuard"

    window.set_capabilities(failed)
    assert window.settings.mode_combo.get_active_id() == "proxy"
    assert window.settings.protocol_combo.get_active_id() == "WireGuard"

    window.apply_connection_settings("warp", "MASQUE")
    assert window.settings.mode_combo.get_active_id() == "warp"
    assert window.settings.protocol_combo.get_active_id() == "MASQUE"
    window.destroy()


def test_destroy_uninstalls_css_provider():
    window = MainWindow(Config(), UIActions())
    window.destroy()

    assert window._provider_binding.screen is None


def test_exact_shipped_trash_svg_is_used_and_close_hides_window():
    window = MainWindow(Config(), UIActions())
    window.set_hosts(("example.com",))
    asset = Path("data/icons/edit-delete.svg")
    assert asset.is_file()
    assert "edit-delete-symbolic" not in asset.read_text(encoding="utf-8")
    assert window.exclusions.delete_icon_path.name == asset.name
    assert window.exclusions.delete_icon_path.read_bytes() == asset.read_bytes()

    window.show_all()
    stopped = window.emit("delete-event", None)
    assert stopped is True
    assert not window.get_visible()
    window.destroy()
