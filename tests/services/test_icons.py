import os
import re
from pathlib import Path

import pytest

from warp_control.config import Config, DEFAULT_COLORS
from warp_control.models import WarpState
from warp_control.services.icons import IconRenderer


TEMPLATE_PATH = Path(__file__).parents[2] / "data" / "icons" / "cloudflare-template.svg"
LEGACY_PATH_GEOMETRY = (
    (
        "M16.493 17.4c.135-.52.08-.983-.161-1.338-.215-.328-.592-.519-1.05-.519"
        "l-8.663-.109a.148.148 0 01-.135-.082c-.027-.054-.027-.109-.027-.163"
        ".027-.082.108-.164.189-.164l8.744-.11c1.05-.054 2.153-.9 2.556-1.937"
        "l.511-1.31c.027-.055.027-.11.027-.164C17.92 8.91 15.66 7 12.942 7"
        "c-2.503 0-4.628 1.638-5.381 3.903a2.432 2.432 0 00-1.803-.491"
        "c-1.21.109-2.153 1.092-2.287 2.32-.027.328 0 .628.054.9"
        "C1.56 13.688 0 15.326 0 17.319c0 .19.027.355.027.545 0 .082.08.137"
        ".161.137h15.983c.08 0 .188-.055.215-.164l.107-.437"
    ),
    (
        "M19.238 11.75h-.242c-.054 0-.108.054-.135.109l-.35 1.2"
        "c-.134.52-.08.983.162 1.338.215.328.592.518 1.05.518l1.855.11"
        "c.054 0 .108.027.135.082.027.054.027.109.027.163-.027.082-.108.164"
        "-.188.164l-1.91.11c-1.05.054-2.153.9-2.557 1.937l-.134.355"
        "c-.027.055.026.137.107.137h6.592c.081 0 .162-.055.162-.137"
        ".107-.41.188-.846.188-1.31-.027-2.62-2.153-4.777-4.762-4.777"
    ),
)


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
    assert tuple(paths) == LEGACY_PATH_GEOMETRY


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


@pytest.mark.parametrize(
    "template",
    [
        '<svg><path fill="{{PRIMARY}}"/></svg>',
        (
            '<svg><path fill="{{PRIMARY}}"/><path fill="{{PRIMARY}}"/>'
            '<path fill="{{SECONDARY}}"/></svg>'
        ),
        (
            '<svg><path fill="{{PRIMARY}}"/><path fill="{{SECONDARY}}"/>'
            '<path fill="{{UNRESOLVED}}"/></svg>'
        ),
    ],
    ids=["missing", "duplicate", "unresolved"],
)
def test_malformed_template_is_rejected_before_output_write(tmp_path, template):
    template_path = tmp_path / "template.svg"
    template_path.write_text(template, encoding="utf-8")
    output_dir = tmp_path / "output"

    with pytest.raises(ValueError, match="template"):
        IconRenderer(template_path, output_dir).render(WarpState.CONNECTED, Config())

    assert not output_dir.exists()
