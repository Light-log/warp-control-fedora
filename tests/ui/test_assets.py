from pathlib import Path

from warp_control.ui.assets import runtime_asset_path


def test_runtime_assets_resolve_from_package_outside_checkout_data_directory():
    trash = runtime_asset_path("edit-delete.svg")
    template = runtime_asset_path("cloudflare-template.svg")

    assert trash.is_file()
    assert template.is_file()
    assert "edit-delete-symbolic" not in trash.read_text(encoding="utf-8")
    assert "{{PRIMARY}}" in template.read_text(encoding="utf-8")
    assert "{{SECONDARY}}" in template.read_text(encoding="utf-8")
    assert trash.parent.name == "assets"
    assert trash.resolve() != Path("data/icons/edit-delete.svg").resolve()
    assert trash.read_bytes() == Path("data/icons/edit-delete.svg").read_bytes()
    assert template.read_bytes() == Path(
        "data/icons/cloudflare-template.svg"
    ).read_bytes()


def test_runtime_asset_directory_can_be_overridden(tmp_path):
    custom = tmp_path / "icons"
    custom.mkdir()

    assert runtime_asset_path("edit-delete.svg", custom) == custom / "edit-delete.svg"


def test_pyproject_packages_both_runtime_svg_assets():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "[tool.setuptools.package-data]" in pyproject
    assert '"warp_control.assets" = ["*.svg"]' in pyproject
