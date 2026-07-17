"""Pure palette and CSS generation, intentionally independent of PyGObject."""

from dataclasses import dataclass

from warp_control.config import Config, DEFAULT_COLORS
from warp_control.models import WarpState


@dataclass(frozen=True)
class Palette:
    header: str
    background: str
    surface: str
    raised: str
    text: str
    muted: str
    border: str


LIGHT_PALETTE = Palette(
    header="#f5f6f8",
    background="#f5f6f8",
    surface="#ffffff",
    raised="#eef1f5",
    text="#172033",
    muted="#667085",
    border="#d7dce3",
)
DARK_PALETTE = Palette(
    header="#0e1726",
    background="#0e1726",
    surface="#162235",
    raised="#1e2d43",
    text="#f8fafc",
    muted="#a7b2c3",
    border="#304058",
)


def palette_for(theme: str) -> Palette:
    return LIGHT_PALETTE if theme == "light" else DARK_PALETTE


def _state_primary(config: Config, state: WarpState) -> str:
    color_key = state.value if state.value in DEFAULT_COLORS else "disconnected"
    configured = config.colors.get(color_key, DEFAULT_COLORS[color_key])
    return configured.get("primary", DEFAULT_COLORS[color_key]["primary"])


def build_css(config: Config, state: WarpState) -> str:
    """Return all application CSS with accent and state roles kept distinct."""
    palette = palette_for(config.theme)
    accent = config.accent
    state_primary = _state_primary(config, state)
    return f"""
window, .app-shell {{
  background-color: {palette.background};
  color: {palette.text};
}}
.integrated-header {{
  background-color: {palette.header};
  color: {palette.text};
  border-bottom: 1px solid {palette.border};
}}
.surface, notebook, notebook > stack {{
  background-color: {palette.surface};
  color: {palette.text};
}}
label.muted {{ color: {palette.muted}; }}
entry, combobox, spinbutton {{
  background-color: {palette.raised};
  color: {palette.text};
  border-color: {palette.border};
}}
.accent-action, button.accent-action {{
  background: {accent};
  background-color: {accent};
  color: #ffffff;
}}
.state-action, button.state-action, .state-badge {{
  background: {state_primary};
  background-color: {state_primary};
  color: #ffffff;
}}
notebook tab:checked {{
  color: {accent};
  border-bottom: 3px solid {accent};
}}
switch:checked slider {{ background-color: #ffffff; }}
switch:checked {{ background-color: {accent}; }}
""".strip()
