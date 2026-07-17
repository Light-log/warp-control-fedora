import os
import re
import stat
import tempfile
from pathlib import Path
from typing import List, Union

from warp_control.config import Config, _load_colors
from warp_control.models import WarpState


_RENDERED_STATES = (
    WarpState.CONNECTED,
    WarpState.CONNECTING,
    WarpState.DISCONNECTED,
    WarpState.ERROR,
)


class IconRenderer:
    """Render state-colored Cloudflare icons from the packaged SVG template."""

    def __init__(self, template_path: Path, output_dir: Path):
        self.template_path = Path(template_path)
        self.output_dir = Path(output_dir)

    def render(self, state: Union[WarpState, str], config: Config) -> Path:
        normalized_state = self._state_or_disconnected(state)
        colors = _load_colors(config.colors)[normalized_state.value]
        primary = colors["primary"]
        secondary = colors["secondary"]
        svg = self._render_template(primary, secondary)

        self._prepare_output_dir()
        target = self.output_dir / f"warp-control-{normalized_state.value}.svg"
        self._refuse_unsafe_target(target)
        self._atomic_write(target, svg)
        return target

    def _render_template(self, primary: str, secondary: str) -> str:
        svg = self.template_path.read_text(encoding="utf-8")
        if svg.count("{{PRIMARY}}") != 1 or svg.count("{{SECONDARY}}") != 1:
            raise ValueError(
                "icon template must contain exactly one primary and secondary marker"
            )
        rendered = svg.replace("{{PRIMARY}}", primary).replace(
            "{{SECONDARY}}", secondary
        )
        if re.search(r"\{\{[^{}]+\}\}", rendered):
            raise ValueError("icon template contains an unresolved marker")
        return rendered

    def render_all(self, config: Config) -> List[Path]:
        return [self.render(state, config) for state in _RENDERED_STATES]

    @staticmethod
    def _state_or_disconnected(state: Union[WarpState, str]) -> WarpState:
        try:
            normalized = WarpState(state)
        except ValueError:
            return WarpState.DISCONNECTED
        if normalized not in _RENDERED_STATES:
            return WarpState.DISCONNECTED
        return normalized

    def _prepare_output_dir(self) -> None:
        if self.output_dir.is_symlink():
            raise OSError(f"refusing symlink output directory: {self.output_dir}")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if not self.output_dir.is_dir():
            raise NotADirectoryError(self.output_dir)

    @staticmethod
    def _refuse_unsafe_target(target: Path) -> None:
        try:
            mode = target.lstat().st_mode
        except FileNotFoundError:
            return
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise OSError(f"refusing non-regular icon target: {target}")

    @staticmethod
    def _atomic_write(target: Path, content: str) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=str(target.parent),
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
                os.fchmod(temporary.fileno(), 0o644)
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, target)
        finally:
            temporary_path.unlink(missing_ok=True)
