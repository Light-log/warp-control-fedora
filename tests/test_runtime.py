"""Tests for portable runtime path resolution."""

from pathlib import Path

import pytest

from warp_control.runtime import RuntimePaths


def test_native_runtime_uses_system_defaults(monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.delenv("WARP_CONTROL_DESKTOP_FILE", raising=False)

    paths = RuntimePaths.from_environment({})

    assert paths.executable == Path("/usr/bin/warp-control")
    assert paths.desktop_source == Path("/usr/share/applications/com.devruby.warpcontrol.desktop")
    assert paths.portable is False


def test_appimage_runtime_uses_original_file(tmp_path):
    image = tmp_path / "WARP-Control.AppImage"
    desktop = tmp_path / "com.devruby.warpcontrol.desktop"

    paths = RuntimePaths.from_environment({
        "APPIMAGE": str(image),
        "WARP_CONTROL_DESKTOP_FILE": str(desktop),
    })

    assert paths.executable == image
    assert paths.desktop_source == desktop
    assert paths.portable is True


def test_appimage_requires_absolute_warp_control_desktop_file(tmp_path):
    image = tmp_path / "WARP-Control.AppImage"

    with pytest.raises(ValueError, match="WARP_CONTROL_DESKTOP_FILE must be absolute"):
        RuntimePaths.from_environment({
            "APPIMAGE": str(image),
            "WARP_CONTROL_DESKTOP_FILE": "relative/path.desktop",
        })


def test_appimage_rejects_missing_warp_control_desktop_file(tmp_path):
    image = tmp_path / "WARP-Control.AppImage"

    with pytest.raises(ValueError, match="WARP_CONTROL_DESKTOP_FILE is invalid"):
        RuntimePaths.from_environment({
            "APPIMAGE": str(image),
            "WARP_CONTROL_DESKTOP_FILE": "",
        })


def test_appimage_rejects_carriage_return_in_path(tmp_path):
    image = tmp_path / "WARP-Control.AppImage"

    with pytest.raises(ValueError, match="APPIMAGE is invalid"):
        RuntimePaths.from_environment({
            "APPIMAGE": f"{image}\r",
        })


def test_appimage_rejects_newline_in_path(tmp_path):
    image = tmp_path / "WARP-Control.AppImage"

    with pytest.raises(ValueError, match="APPIMAGE is invalid"):
        RuntimePaths.from_environment({
            "APPIMAGE": f"{image}\n",
            "WARP_CONTROL_DESKTOP_FILE": str(tmp_path / "desktop"),
        })


def test_appimage_rejects_nul_in_path(tmp_path):
    image = tmp_path / "WARP-Control.AppImage"

    with pytest.raises(ValueError, match="APPIMAGE is invalid"):
        RuntimePaths.from_environment({
            "APPIMAGE": f"{image}\0extra",
            "WARP_CONTROL_DESKTOP_FILE": str(tmp_path / "desktop"),
        })


def test_appimage_rejects_relative_appimage_path(tmp_path):
    desktop = tmp_path / "com.devruby.warpcontrol.desktop"

    with pytest.raises(ValueError, match="APPIMAGE must be absolute"):
        RuntimePaths.from_environment({
            "APPIMAGE": "relative/path.AppImage",
            "WARP_CONTROL_DESKTOP_FILE": str(desktop),
        })


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("APPIMAGE", "/tmp/.mount_WARP123/AppRun"),
        (
            "WARP_CONTROL_DESKTOP_FILE",
            "/tmp/.mount_WARP123/usr/share/applications/com.devruby.warpcontrol.desktop",
        ),
    ],
)
def test_appimage_rejects_ephemeral_mount_paths(variable, value):
    environment = {
        "APPIMAGE": "/opt/WARP-Control.AppImage",
        "WARP_CONTROL_DESKTOP_FILE": "/opt/com.devruby.warpcontrol.desktop",
    }
    environment[variable] = value

    with pytest.raises(ValueError, match="must not reference an AppImage mount path"):
        RuntimePaths.from_environment(environment)


def test_desktop_source_control_character_rejection(tmp_path):
    image = tmp_path / "WARP-Control.AppImage"
    desktop = tmp_path / "com.devruby.warpcontrol.desktop"

    with pytest.raises(ValueError, match="WARP_CONTROL_DESKTOP_FILE is invalid"):
        RuntimePaths.from_environment({
            "APPIMAGE": str(image),
            "WARP_CONTROL_DESKTOP_FILE": f"{desktop}\r",
        })
