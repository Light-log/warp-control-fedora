import configparser
import os
from pathlib import Path

import pytest

from warp_control.services.autostart import AutostartService


DESKTOP_SOURCE = """[Desktop Entry]
Name=WARP Control
Exec=/some/installed/warp-control
Icon=com.devruby.warpcontrol
Type=Application
Categories=Network;Utility;
StartupNotify=false
"""


def service(tmp_path, **kwargs):
    source = tmp_path / "installed.desktop"
    source.write_text(DESKTOP_SOURCE, encoding="utf-8")
    kwargs.setdefault("exec_path", "/usr/bin/warp-control")
    kwargs.setdefault("desktop_source", source)
    return AutostartService(
        config_home=tmp_path / "config",
        **kwargs,
    )


def test_installed_desktop_entry_has_exact_required_metadata():
    desktop_path = Path(__file__).parents[2] / "data" / "com.devruby.warpcontrol.desktop"
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read_string(desktop_path.read_text(encoding="utf-8"))

    assert parser.sections() == ["Desktop Entry"]
    assert dict(parser["Desktop Entry"]) == {
        "Type": "Application",
        "Name": "WARP Control",
        "Exec": "/usr/bin/warp-control",
        "Icon": "com.devruby.warpcontrol",
        "Categories": "Network;Utility;",
        "StartupNotify": "false",
    }


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


def test_relative_xdg_config_home_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/config")
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


def test_enable_serializes_reserved_executable_path_characters(tmp_path):
    executable = Path('/opt/WARP Control/warp "quote"\\slash%$`')
    autostart = service(tmp_path, exec_path=executable)

    path = autostart.enable()
    persisted = path.read_text(encoding="utf-8")
    expected_exec = r'Exec="/opt/WARP Control/warp \\"quote\\"\\\\slash%%\\$\\`" --background'

    assert expected_exec in persisted.splitlines()
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read_string(persisted)
    assert parser["Desktop Entry"]["Exec"] == expected_exec.removeprefix("Exec=")
    assert parser["Desktop Entry"]["Name"] == "WARP Control"


def test_enable_rejects_control_character_in_executable_path(tmp_path):
    autostart = service(tmp_path, exec_path=tmp_path / "warp\ncontrol")

    with pytest.raises(ValueError, match="exec_path is invalid"):
        autostart.enable()


@pytest.mark.parametrize(
    ("executable", "error"),
    [
        (Path("/opt/warp=control"), "must not contain '='"),
        (Path("/opt/warp-control-ñ"), "printable ASCII"),
    ],
)
def test_enable_rejects_nonconforming_executable_path(executable, error, tmp_path):
    autostart = service(tmp_path, exec_path=executable)

    with pytest.raises(ValueError, match=error):
        autostart.enable()


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


def test_autostart_uses_stable_appimage_executable_path(tmp_path):
    """Verify autostart receives stable AppImage path, not /tmp/.mount."""
    from warp_control.runtime import RuntimePaths

    image = tmp_path / "WARP-Control-2.0.0-x86_64.AppImage"
    desktop = tmp_path / "com.devruby.warpcontrol.desktop"
    desktop.write_text(DESKTOP_SOURCE, encoding="utf-8")

    paths = RuntimePaths.from_environment({
        "APPIMAGE": str(image),
        "WARP_CONTROL_DESKTOP_FILE": str(desktop),
    })

    autostart = service(tmp_path, exec_path=paths.executable)
    assert autostart.exec_path == image
    assert "/tmp/.mount" not in str(autostart.exec_path)


def test_autostart_receives_runtime_paths_for_portable(tmp_path):
    """Verify autostart uses custom desktop_source from RuntimePaths."""
    from warp_control.runtime import RuntimePaths

    image = tmp_path / "WARP-Control.AppImage"
    desktop = tmp_path / "portable.desktop"
    desktop.write_text(DESKTOP_SOURCE, encoding="utf-8")

    paths = RuntimePaths.from_environment({
        "APPIMAGE": str(image),
        "WARP_CONTROL_DESKTOP_FILE": str(desktop),
    })

    autostart = service(tmp_path, desktop_source=paths.desktop_source, exec_path=paths.executable)
    assert autostart.desktop_source == desktop
    assert autostart.exec_path == image


def test_autostart_respects_native_defaults_without_appimage(tmp_path):
    """Verify autostart uses native defaults when APPIMAGE is not set."""
    from warp_control.runtime import RuntimePaths

    paths = RuntimePaths.from_environment({})

    assert paths.executable == Path("/usr/bin/warp-control")
    assert paths.desktop_source == Path("/usr/share/applications/com.devruby.warpcontrol.desktop")
    assert paths.portable is False
