import os
import re
from pathlib import Path

import pytest

from warp_control.config import Config, DEFAULT_COLORS
from warp_control.models import WarpState
from warp_control.services.icons import IconRenderer


TEMPLATE_PATH = Path(__file__).parents[2] / "data" / "icons" / "cloudflare-template.svg"


@pytest.mark.parametrize(
    "state",
    [
        WarpState.CONNECTED,
        WarpState.CONNECTING,
        WarpState.DISCONNECTED,
        WarpState.ERROR,
    ],
)
def test_render_uses_exact_state_colors_and_never_accent(tmp_path, state):
    config = Config(accent="#010101")
    config.colors[state.value] = {
        "primary": "#123456",
        "secondary": "#ABCDEF",
    }

    path = IconRenderer(TEMPLATE_PATH, tmp_path).render(state, config)
    svg = path.read_text(encoding="utf-8")

    assert path == tmp_path / f"warp-control-{state.value}.svg"
    assert re.findall(r'fill="(#[0-9A-F]{6})"', svg) == [
        "#123456",
        "#ABCDEF",
    ]
    assert config.accent not in svg
    assert path.stat().st_mode & 0o777 == 0o644


def test_render_is_deterministic_and_template_contains_installer_geometry(tmp_path):
    renderer = IconRenderer(TEMPLATE_PATH, tmp_path)
    config = Config()

    first = renderer.render(WarpState.CONNECTED, config).read_bytes()
    second = renderer.render(WarpState.CONNECTED, config).read_bytes()

    assert first == second
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    paths = re.findall(r'<path d="([^"]+)"', template)
    assert len(paths) == 2
    assert paths[0].startswith("M16.493 17.4c.135-.52")
    assert paths[1].startswith("M19.238 11.75h-.242")


def test_unknown_state_uses_disconnected_name_and_colors(tmp_path):
    config = Config()

    path = IconRenderer(TEMPLATE_PATH, tmp_path).render(WarpState.UNKNOWN, config)
    svg = path.read_text(encoding="utf-8")

    assert path.name == "warp-control-disconnected.svg"
    assert DEFAULT_COLORS["disconnected"]["primary"] in svg
    assert DEFAULT_COLORS["disconnected"]["secondary"] in svg


def test_render_validates_colors_with_config_fallbacks(tmp_path):
    config = Config()
    config.colors["error"] = {"primary": "bad", "secondary": "#010203"}

    svg = (
        IconRenderer(TEMPLATE_PATH, tmp_path)
        .render(WarpState.ERROR, config)
        .read_text(encoding="utf-8")
    )

    assert DEFAULT_COLORS["error"]["primary"] in svg
    assert "#010203" in svg


def test_render_treats_malformed_state_color_mapping_like_config_load(tmp_path):
    config = Config()
    config.colors["error"] = "not-a-color-mapping"

    svg = (
        IconRenderer(TEMPLATE_PATH, tmp_path)
        .render(WarpState.ERROR, config)
        .read_text(encoding="utf-8")
    )

    assert DEFAULT_COLORS["error"]["primary"] in svg
    assert DEFAULT_COLORS["error"]["secondary"] in svg


def test_render_all_creates_every_concrete_state_in_stable_order(tmp_path):
    paths = IconRenderer(TEMPLATE_PATH, tmp_path).render_all(Config())

    assert [path.name for path in paths] == [
        "warp-control-connected.svg",
        "warp-control-connecting.svg",
        "warp-control-disconnected.svg",
        "warp-control-error.svg",
    ]


def test_atomic_replace_failure_preserves_original_and_cleans_temp(
    tmp_path, monkeypatch
):
    target = tmp_path / "warp-control-connected.svg"
    target.write_text("original", encoding="utf-8")

    def fail_replace(source, destination):
        assert Path(destination) == target
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        IconRenderer(TEMPLATE_PATH, tmp_path).render(WarpState.CONNECTED, Config())

    assert target.read_text(encoding="utf-8") == "original"
    assert list(tmp_path.glob(".*.tmp")) == []


def test_renderer_refuses_symlink_output_directory_and_target(tmp_path):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    linked_dir = tmp_path / "linked"
    linked_dir.symlink_to(real_dir, target_is_directory=True)

    with pytest.raises(OSError):
        IconRenderer(TEMPLATE_PATH, linked_dir).render(WarpState.CONNECTED, Config())

    target = real_dir / "warp-control-connected.svg"
    target.symlink_to(tmp_path / "elsewhere.svg")
    with pytest.raises(OSError):
        IconRenderer(TEMPLATE_PATH, real_dir).render(WarpState.CONNECTED, Config())
