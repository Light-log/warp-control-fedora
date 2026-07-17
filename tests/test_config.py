import builtins
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

import warp_control.config as config_module
from warp_control.config import Config, DEFAULT_COLORS


def test_defaults_use_approved_schema_and_palette(tmp_path):
    config = Config.load(tmp_path / "config.json")

    assert config.schema_version == 2
    assert config.theme == "dark"
    assert config.accent == "#F38020"
    assert config.colors == {
        "connected": {"primary": "#16A34A", "secondary": "#4ADE80"},
        "connecting": {"primary": "#F38020", "secondary": "#FCAD32"},
        "disconnected": {"primary": "#64748B", "secondary": "#94A3B8"},
        "error": {"primary": "#DC2626", "secondary": "#F87171"},
    }
    assert config.autostart_enabled is True
    assert config.auto_update_enabled is True
    assert config.update_interval_seconds == 5


def test_load_uses_xdg_config_home_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    expected = tmp_path / "warp-control" / "config.json"
    expected.parent.mkdir(parents=True)
    expected.write_text('{"theme": "light"}', encoding="utf-8")

    config = Config.load()

    assert config.path == expected
    assert config.theme == "light"


def test_load_uses_home_config_directory_when_xdg_is_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    config = Config.load()

    assert config.path == tmp_path / ".config" / "warp-control" / "config.json"


def test_schema_less_config_is_migrated_without_losing_valid_values(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "theme": "light",
                "accent": "#445566",
                "colors": {
                    "connected": {
                        "primary": "#112233",
                        "secondary": "#AABBCC",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    config = Config.load(path)

    assert config.schema_version == 2
    assert config.theme == "light"
    assert config.accent == "#445566"
    assert config.colors["connected"] == {
        "primary": "#112233",
        "secondary": "#AABBCC",
    }
    assert config.colors["error"] == DEFAULT_COLORS["error"]


def test_invalid_values_fall_back_independently(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "old",
                "theme": "blue",
                "accent": "F38020",
                "colors": {
                    "connected": {
                        "primary": "#12345G",
                        "secondary": "#010203",
                    },
                    "connecting": "orange",
                },
                "autostart_enabled": "yes",
                "auto_update_enabled": False,
                "update_interval_seconds": 0,
            }
        ),
        encoding="utf-8",
    )

    config = Config.load(path)

    assert config.schema_version == 2
    assert config.theme == "dark"
    assert config.accent == "#F38020"
    assert config.colors["connected"] == {
        "primary": DEFAULT_COLORS["connected"]["primary"],
        "secondary": "#010203",
    }
    assert config.colors["connecting"] == DEFAULT_COLORS["connecting"]
    assert config.autostart_enabled is True
    assert config.auto_update_enabled is False
    assert config.update_interval_seconds == 5


def test_malformed_json_uses_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("not json", encoding="utf-8")

    config = Config.load(path)

    assert config.theme == "dark"
    assert config.colors == DEFAULT_COLORS


def test_load_propagates_permission_error_without_changing_file(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    original = b'{"theme":"light"}'
    path.write_bytes(original)
    real_read_text = Path.read_text

    def denied_read_text(self, *args, **kwargs):
        if self == path:
            raise PermissionError("denied")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied_read_text)

    with pytest.raises(PermissionError, match="denied"):
        Config.load(path)

    assert path.read_bytes() == original


def test_load_rejects_future_schema_without_changing_file(tmp_path):
    path = tmp_path / "config.json"
    original = b'{"schema_version":3,"future_setting":{"keep":true}}'
    path.write_bytes(original)

    with pytest.raises(config_module.UnsupportedConfigVersionError, match="3"):
        Config.load(path)

    assert path.read_bytes() == original


def test_save_and_reload_round_trip(tmp_path):
    path = tmp_path / "nested" / "config.json"
    config = Config.load(path)
    config.theme = "light"
    config.accent = "#ABCDEF"
    config.update_interval_seconds = 30

    config.save()
    reloaded = Config.load(path)

    assert reloaded.theme == "light"
    assert reloaded.accent == "#ABCDEF"
    assert reloaded.update_interval_seconds == 30


def test_save_atomically_replaces_with_sibling_temp_file(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "config.json"
    config = Config.load(path)
    calls = []
    real_replace = os.replace

    def recording_replace(source, destination):
        source = type(path)(source)
        destination = type(path)(destination)
        calls.append((source, destination, source.exists()))
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", recording_replace)

    config.save()

    assert len(calls) == 1
    source, destination, existed_at_replace = calls[0]
    assert existed_at_replace is True
    assert source.parent == path.parent
    assert source != path
    assert destination == path
    assert not source.exists()


def test_save_normalizes_invalid_public_mutations(tmp_path):
    path = tmp_path / "config.json"
    config = Config.load(path)
    config.theme = "sepia"
    config.accent = "#NOTHEX"
    config.colors = {
        "connected": {"primary": "bad", "secondary": "#010203"},
        "connecting": {"primary": "#ABCDEF", "secondary": None},
        "error": "red",
    }
    config.autostart_enabled = 1
    config.auto_update_enabled = "false"
    config.update_interval_seconds = True

    config.save()

    assert config.theme == "dark"
    assert config.accent == "#F38020"
    assert config.colors["connected"] == {
        "primary": DEFAULT_COLORS["connected"]["primary"],
        "secondary": "#010203",
    }
    assert config.colors["connecting"] == {
        "primary": "#ABCDEF",
        "secondary": DEFAULT_COLORS["connecting"]["secondary"],
    }
    assert config.colors["disconnected"] == DEFAULT_COLORS["disconnected"]
    assert config.colors["error"] == DEFAULT_COLORS["error"]
    assert config.autostart_enabled is True
    assert config.auto_update_enabled is True
    assert config.update_interval_seconds == 5
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "schema_version": 2,
        "theme": config.theme,
        "accent": config.accent,
        "colors": config.colors,
        "autostart_enabled": config.autostart_enabled,
        "auto_update_enabled": config.auto_update_enabled,
        "update_interval_seconds": config.update_interval_seconds,
    }
    assert Config.load(path) == config


def test_save_replace_failure_preserves_original_and_cleans_temp(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    original = b'{"schema_version":2,"theme":"dark"}'
    path.write_bytes(original)
    config = Config.load(path)
    config.theme = "light"

    def failed_replace(source, destination):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", failed_replace)

    with pytest.raises(OSError, match="replace failed"):
        config.save()

    assert path.read_bytes() == original
    assert list(tmp_path.glob(f".{path.name}.*.tmp")) == []


def test_reset_restores_defaults_and_persists_them(tmp_path):
    path = tmp_path / "config.json"
    config = Config.load(path)
    config.theme = "light"
    config.accent = "#ABCDEF"
    config.autostart_enabled = False
    config.colors["error"]["primary"] = "#000000"
    config.save()

    config.reset()

    assert config.theme == "dark"
    assert config.accent == "#F38020"
    assert config.autostart_enabled is True
    assert config.colors == DEFAULT_COLORS
    assert Config.load(path).colors == DEFAULT_COLORS


def test_importing_package_does_not_import_gi():
    script = "import sys; import warp_control; assert 'gi' not in sys.modules"
    environment = os.environ.copy()
    source_path = str(Path(__file__).parents[1] / "src")
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        source_path
        if existing_pythonpath is None
        else source_path + os.pathsep + existing_pythonpath
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr


def test_main_module_import_is_lazy(monkeypatch):
    real_import = builtins.__import__

    def reject_app_import(name, *args, **kwargs):
        if name == "warp_control.app":
            pytest.fail("warp_control.app was imported eagerly")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_app_import)

    __import__("warp_control.__main__")


def test_main_delegates_to_app_and_propagates_return_value(monkeypatch):
    import warp_control.__main__ as entry_point

    calls = []

    def fake_main():
        calls.append("called")
        return 23

    fake_app = types.ModuleType("warp_control.app")
    fake_app.main = fake_main
    monkeypatch.setitem(sys.modules, "warp_control.app", fake_app)

    result = entry_point.main()

    assert calls == ["called"]
    assert result == 23


def test_pyproject_declares_package_tooling_contract():
    pyproject_path = Path(__file__).parents[1] / "pyproject.toml"
    pyproject = pyproject_path.read_text(encoding="utf-8")

    def section(name):
        marker = f"[{name}]\n"
        assert marker in pyproject
        return pyproject.split(marker, 1)[1].split("\n[", 1)[0]

    assert 'build-backend = "setuptools.build_meta"' in section("build-system")
    assert 'requires-python = ">=3.9"' in section("project")
    assert (
        'warp-control = "warp_control.__main__:main"'
        in section("project.scripts")
    )
    assert 'pythonpath = ["src"]' in section("tool.pytest.ini_options")
    assert 'target-version = "py39"' in section("tool.ruff")
