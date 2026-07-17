"""Pure UI presentation models and callback contracts."""

from dataclasses import dataclass
from typing import Callable

from warp_control.models import WarpState


CONFIG_WIDTH = 420
CONFIG_CONTENT_HEIGHT = 390


def _noop(*args: object) -> None:
    return None


@dataclass(frozen=True)
class StatePresentation:
    status_label: str
    action_label: str
    action_sensitive: bool


_STATE_PRESENTATIONS = {
    WarpState.CONNECTED: StatePresentation("Conectado", "Desconectar", True),
    WarpState.CONNECTING: StatePresentation("Conectando…", "Conectando…", False),
    WarpState.DISCONNECTED: StatePresentation("Desconectado", "Conectar", True),
    WarpState.ERROR: StatePresentation("Error de conexión", "Reintentar", True),
    WarpState.UNKNOWN: StatePresentation("Estado desconocido", "Conectar", True),
}


def present_state(state: WarpState) -> StatePresentation:
    return _STATE_PRESENTATIONS.get(state, _STATE_PRESENTATIONS[WarpState.UNKNOWN])


@dataclass(frozen=True)
class UIActions:
    """All external effects injected into the otherwise passive GTK views."""

    on_toggle_connection: Callable[[], None] = _noop
    on_add_host: Callable[[str, bool], None] = _noop
    on_remove_host: Callable[[str], None] = _noop
    on_theme_changed: Callable[[str], None] = _noop
    on_color_changed: Callable[[str, str, str], None] = _noop
    on_accent_changed: Callable[[str], None] = _noop
    on_reset_appearance: Callable[[], None] = _noop
    on_autostart_changed: Callable[[bool], None] = _noop
    on_auto_update_changed: Callable[[bool], None] = _noop
    on_interval_changed: Callable[[int], None] = _noop
    on_mode_changed: Callable[[str], None] = _noop
    on_protocol_changed: Callable[[str], None] = _noop
    on_restart_service: Callable[[], None] = _noop
    on_test_connection: Callable[[], None] = _noop
    on_open_log: Callable[[], None] = _noop
