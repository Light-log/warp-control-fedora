"""Documentation contracts that are cheap to verify in every checkout."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def release_version() -> str:
    values = dict(
        line.split("=", 1)
        for line in (ROOT / "packaging" / "release.env").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    return values["VERSION"]


def test_readme_links_to_the_supported_installation_material() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for target in ("docs/INSTALL.md", "docs/ARCHITECTURE.md", "docs/SUPPORT.md"):
        assert target in readme


def test_documented_preview_gallery_is_complete() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    screenshot_dir = ROOT / "docs" / "screenshots"
    expected = {
        f"{theme}-{page}.png"
        for theme in ("dark", "light")
        for page in ("exclusions", "appearance", "settings")
    }
    assert {item.name for item in screenshot_dir.glob("*.png")} == expected
    for name in expected:
        assert f"docs/screenshots/{name}" in readme


def test_readme_documents_all_linux_release_families() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    release_rows = [
        line
        for line in readme.splitlines()
        if line.startswith("| **") and any(kind in line for kind in ("RPM", "DEB", "Arch", "AppImage"))
    ]
    assert len(release_rows) == 4
    for kind in ("RPM", "DEB", "Arch", "AppImage"):
        assert sum(kind in row for row in release_rows) == 1
    for label in ("Oficial", "Comunitario", "Portátil"):
        assert label in readme


def test_installation_docs_match_the_release_contract() -> None:
    install = (ROOT / "docs" / "INSTALL.md").read_text(encoding="utf-8")
    version = release_version()
    required_names = (
        f"warp-control-{version}.tar.gz",
        f"warp-control-{version}-1.fc43.noarch.rpm",
        f"warp-control-{version}-1.fc44.noarch.rpm",
        f"warp-control-{version}-1.el9.noarch.rpm",
        f"warp-control-{version}-1.el10.noarch.rpm",
        f"warp-control_{version}-1_all-ubuntu2204.deb",
        f"warp-control_{version}-1_all-ubuntu2404.deb",
        f"warp-control_{version}-1_all-ubuntu2604.deb",
        f"warp-control_{version}-1_all-debian12.deb",
        f"warp-control_{version}-1_all-debian13.deb",
        f"warp-control-{version}-1-any.pkg.tar.zst",
        f"WARP-Control-{version}-x86_64.AppImage",
        f"WARP-Control-{version}-aarch64.AppImage",
    )
    for name in required_names:
        assert name in install
    assert "sha256sum -c SHA256SUMS" in install


def test_support_scope_is_explicit() -> None:
    support = (ROOT / "docs" / "SUPPORT.md").read_text(encoding="utf-8")
    normalized = " ".join(support.split())
    assert "Linux" in support
    assert "Windows" in support
    assert "macOS" in support
    assert "AppImage" in support
    assert "no amplía el soporte oficial" in normalized


def test_ci_keeps_quality_and_package_jobs_separate() -> None:
    quality = (ROOT / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")
    packages = (ROOT / ".github" / "workflows" / "packages.yml").read_text(encoding="utf-8")
    assert "python -m pytest -q" in quality
    for job in ("rpm:", "deb:", "arch:"):
        assert job in packages
