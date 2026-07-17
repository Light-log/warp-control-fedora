from warp_control.models import WarpState
from pathlib import Path

from warp_control.ui.presenters import (
    CONFIG_CONTENT_HEIGHT,
    CONFIG_WIDTH,
    MODE_LABELS,
    UIActions,
    normalize_icon_path,
    present_state,
)


def test_presenter_maps_every_warp_state_to_spanish_ui():
    expected = {
        WarpState.CONNECTED: ("Conectado", "Desconectar", True),
        WarpState.CONNECTING: ("Conectando…", "Conectando…", False),
        WarpState.DISCONNECTED: ("Desconectado", "Conectar", True),
        WarpState.ERROR: ("Error de conexión", "Reintentar", True),
        WarpState.UNKNOWN: ("Estado desconocido", "Conectar", True),
    }

    assert {
        state: (
            present_state(state).status_label,
            present_state(state).action_label,
            present_state(state).action_sensitive,
        )
        for state in WarpState
    } == expected


def test_layout_contract_is_fixed_to_approved_width_and_viewport():
    assert CONFIG_WIDTH == 420
    assert CONFIG_CONTENT_HEIGHT > 0


def test_callback_model_has_safe_noop_defaults_and_preserves_injected_callbacks():
    calls = []
    actions = UIActions(on_add_host=lambda host, subdomains: calls.append((host, subdomains)))

    actions.on_add_host("example.com", True)
    actions.on_toggle_connection()
    actions.on_open_log()

    assert calls == [("example.com", True)]


def test_state_icon_path_contract_accepts_path_and_string():
    assert normalize_icon_path(Path("state.svg")) == "state.svg"
    assert normalize_icon_path("/tmp/connected.svg") == "/tmp/connected.svg"


def test_warp_mode_uses_exact_approved_spanish_label():
    assert MODE_LABELS["warp"] == "WARP con DNS UDP"


def test_compact_panel_uses_gtk3_widget_naming_api():
    source = Path("src/warp_control/ui/compact_panel.py").read_text(encoding="utf-8")

    assert ".set_name(" in source
    assert ".set_widget_name(" not in source
