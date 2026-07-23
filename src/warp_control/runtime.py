"""Portable runtime path resolution for native and AppImage environments."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


NATIVE_EXECUTABLE = Path("/usr/bin/warp-control")
NATIVE_DESKTOP_SOURCE = Path(
    "/usr/share/applications/com.devruby.warpcontrol.desktop"
)


def _is_appimage_mount_path(path: Path) -> bool:
    """Identify AppImage's ephemeral mount directory without rejecting /tmp."""
    components = path.as_posix().split("/")
    while components and not components[0]:
        components.pop(0)
    return (
        bool(components)
        and components[0] == "tmp"
        and any(component.startswith(".mount_") for component in components[1:])
    )


def _absolute_path(value: str, label: str) -> Path:
    """Return a safe absolute runtime path without resolving symlinks."""
    if not value or any(character in value for character in "\r\n\0"):
        raise ValueError(f"{label} is invalid")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute")
    if _is_appimage_mount_path(path):
        raise ValueError(f"{label} must not reference an AppImage mount path")
    return path


@dataclass(frozen=True)
class RuntimePaths:
    executable: Path
    desktop_source: Path
    portable: bool

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] = os.environ
    ) -> "RuntimePaths":
        appimage = environment.get("APPIMAGE")
        if not appimage:
            return cls(NATIVE_EXECUTABLE, NATIVE_DESKTOP_SOURCE, False)

        return cls(
            _absolute_path(appimage, "APPIMAGE"),
            _absolute_path(
                environment.get("WARP_CONTROL_DESKTOP_FILE", ""),
                "WARP_CONTROL_DESKTOP_FILE",
            ),
            True,
        )
