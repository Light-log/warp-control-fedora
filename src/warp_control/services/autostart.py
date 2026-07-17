import os
import stat
import tempfile
from pathlib import Path
from typing import Optional


DEFAULT_DESKTOP_SOURCE = Path("/usr/share/applications/com.robler.warpcontrol.desktop")


def _default_config_home() -> Path:
    configured = os.environ.get("XDG_CONFIG_HOME")
    return Path(configured) if configured else Path.home() / ".config"


class AutostartService:
    """Manage WARP Control's per-user freedesktop autostart entry."""

    def __init__(
        self,
        config_home: Optional[Path] = None,
        path: Optional[Path] = None,
        desktop_source: Optional[Path] = None,
        exec_path: Path = Path("/usr/bin/warp-control"),
    ):
        base = Path(config_home) if config_home is not None else _default_config_home()
        self.path = (
            Path(path)
            if path is not None
            else base / "autostart" / "warp-control.desktop"
        )
        self.desktop_source = (
            Path(desktop_source)
            if desktop_source is not None
            else DEFAULT_DESKTOP_SOURCE
        )
        self.exec_path = Path(exec_path)

    def enable(self) -> Path:
        source = self.desktop_source.read_text(encoding="utf-8")
        content = self._autostart_content(source)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._refuse_unsafe_target()
        self._atomic_write(content)
        return self.path

    def disable(self) -> None:
        if not self._refuse_unsafe_target():
            return
        self.path.unlink()

    def is_enabled(self) -> bool:
        if not self._refuse_unsafe_target():
            return False
        return (
            "X-GNOME-Autostart-enabled=true"
            in self.path.read_text(encoding="utf-8").splitlines()
        )

    def _autostart_content(self, source: str) -> str:
        lines = source.splitlines()
        replaced_exec = False
        found_enabled = False
        for index, line in enumerate(lines):
            if line.startswith("Exec="):
                lines[index] = f"Exec={self.exec_path} --background"
                replaced_exec = True
            elif line.startswith("X-GNOME-Autostart-enabled="):
                lines[index] = "X-GNOME-Autostart-enabled=true"
                found_enabled = True
        if not replaced_exec:
            raise ValueError("desktop source has no Exec entry")
        if not found_enabled:
            lines.append("X-GNOME-Autostart-enabled=true")
        return "\n".join(lines) + "\n"

    def _refuse_unsafe_target(self) -> bool:
        try:
            mode = self.path.lstat().st_mode
        except FileNotFoundError:
            return False
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise OSError(f"refusing non-regular autostart target: {self.path}")
        return True

    def _atomic_write(self, content: str) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=str(self.path.parent),
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
                os.fchmod(temporary.fileno(), 0o644)
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.path)
        finally:
            temporary_path.unlink(missing_ok=True)
