"""Documentation contracts that are cheap to verify in every checkout."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_links_to_the_supported_installation_material() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for target in ("docs/INSTALL.md", "docs/ARCHITECTURE.md", "docs/SUPPORT.md"):
        assert target in readme


def test_documented_preview_gallery_is_complete() -> None:
    screenshot_dir = ROOT / "docs" / "screenshots"
    expected = {
        f"{theme}-{page}.png"
        for theme in ("dark", "light")
        for page in ("exclusions", "appearance", "settings")
    }
    assert {item.name for item in screenshot_dir.glob("*.png")} == expected


def test_ci_keeps_quality_and_package_jobs_separate() -> None:
    quality = (ROOT / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")
    packages = (ROOT / ".github" / "workflows" / "packages.yml").read_text(encoding="utf-8")
    assert "python -m pytest -q" in quality
    for job in ("rpm:", "deb:", "arch:"):
        assert job in packages
