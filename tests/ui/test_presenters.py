from warp_control.models import WarpState
from warp_control.ui.presenters import (
    CONFIG_CONTENT_HEIGHT,
    CONFIG_WIDTH,
    UIActions,
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

