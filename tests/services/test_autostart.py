import os
from pathlib import Path

import pytest

from warp_control.services.autostart import AutostartService


DESKTOP_SOURCE = """[Desktop Entry]
Name=WARP Control
Exec=/some/installed/warp-control
Icon=com.robler.warpcontrol
Type=Application
Categories=Network;Utility;
StartupNotify=false
"""


def service(tmp_path, **kwargs):
    source = tmp_path / "installed.desktop"
    source.write_text(DESKTOP_SOURCE, encoding="utf-8")
    return AutostartService(
        config_home=tmp_path / "config",
        desktop_source=source,
        exec_path="/usr/bin/warp-control",
        **kwargs,
    )


def test_default_path_prefers_xdg_config_home(tmp_path, monkeypatch):
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    assert AutostartService().path == xdg / "autostart" / "warp-control.desktop"


def test_default_path_falls_back_to_home_config(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    assert AutostartService().path == (
        tmp_path / "home" / ".config" / "autostart" / "warp-control.desktop"
    )


def test_explicit_path_takes_precedence_over_config_home(tmp_path):
    explicit = tmp_path / "custom.desktop"

    assert service(tmp_path, path=explicit).path == explicit


def test_enable_creates_expected_entry_atomically_with_mode(tmp_path):
    autostart = service(tmp_path)

    path = autostart.enable()

    assert path == tmp_path / "config" / "autostart" / "warp-control.desktop"
    assert (
        path.read_text(encoding="utf-8")
        == DESKTOP_SOURCE.replace(
            "Exec=/some/installed/warp-control",
            "Exec=/usr/bin/warp-control --background",
        )
        + "X-GNOME-Autostart-enabled=true\n"
    )
    assert path.stat().st_mode & 0o777 == 0o644
    assert autostart.is_enabled() is True


def test_enable_and_disable_are_idempotent(tmp_path):
    autostart = service(tmp_path)

    first = autostart.enable().read_bytes()
    second = autostart.enable().read_bytes()
    autostart.disable()
    autostart.disable()

    assert first == second
    assert autostart.is_enabled() is False


@pytest.mark.parametrize("method", ["enable", "disable", "is_enabled"])
def test_operations_refuse_symlink_target(tmp_path, method):
    autostart = service(tmp_path)
    autostart.path.parent.mkdir(parents=True)
    autostart.path.symlink_to(tmp_path / "victim.desktop")

    with pytest.raises(OSError):
        getattr(autostart, method)()


def test_atomic_replace_failure_preserves_original_and_cleans_temp(
    tmp_path, monkeypatch
):
    autostart = service(tmp_path)
    autostart.path.parent.mkdir(parents=True)
    autostart.path.write_text("original", encoding="utf-8")

    def fail_replace(source, destination):
        assert Path(destination) == autostart.path
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        autostart.enable()

    assert autostart.path.read_text(encoding="utf-8") == "original"
    assert list(autostart.path.parent.glob(".*.tmp")) == []


def test_enable_propagates_missing_source_error(tmp_path):
    autostart = AutostartService(
        config_home=tmp_path,
        desktop_source=tmp_path / "missing.desktop",
    )

    with pytest.raises(FileNotFoundError):
        autostart.enable()
