from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


ROOT = Path(__file__).parents[2]
SPEC = ROOT / "packaging/rpm/warp-control.spec"


def test_wheel_contains_runtime_assets_and_console_entry_point(tmp_path: Path) -> None:
    wheel_dir = tmp_path / "wheel"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(wheel_dir),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    wheel = next(wheel_dir.glob("warp_control-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        entry_points = archive.read(
            "warp_control-2.0.0.dist-info/entry_points.txt"
        ).decode()

    assert "warp_control/assets/cloudflare-template.svg" in names
    assert "warp_control/assets/cloudflare-fallback.svg" in names
    assert "warp_control/assets/edit-delete.svg" in names
    assert "warp-control = warp_control.__main__:main" in entry_points


def test_rpm_spec_uses_pyproject_macros_and_explicit_native_layout() -> None:
    spec = SPEC.read_text(encoding="utf-8")

    for required in (
        "BuildArch:      noarch",
        "%pyproject_buildrequires",
        "%pyproject_wheel",
        "%pyproject_install",
        "%pyproject_save_files warp_control",
        "%{_bindir}/warp-control",
        "%{_datadir}/applications/com.robler.warpcontrol.desktop",
        "%{_metainfodir}/com.robler.warpcontrol.metainfo.xml",
        "%{_datadir}/icons/hicolor/scalable/apps/com.robler.warpcontrol.svg",
        "%{_datadir}/polkit-1/actions/com.robler.warpcontrol.policy",
        "%{_libexecdir}/warp-control/install-warp",
        "%{_libexecdir}/warp-control/restart-warp",
    ):
        assert required in spec

    assert "Requires:       cloudflare-warp" not in spec
    for dependency in (
        "python3-gobject",
        "gtk3",
        "libayatana-appindicator-gtk3",
        "python3-idna",
        "polkit",
    ):
        assert f"Requires:       {dependency}" in spec


def test_appstream_metadata_identifies_the_desktop_application() -> None:
    root = ET.parse(ROOT / "data/com.robler.warpcontrol.metainfo.xml").getroot()

    assert root.attrib["type"] == "desktop-application"
    assert root.findtext("id") == "com.robler.warpcontrol"
    assert root.findtext("metadata_license") == "CC0-1.0"
    assert root.findtext("project_license") == "MIT"
    launchable = root.find("launchable")
    assert launchable is not None
    assert launchable.attrib["type"] == "desktop-id"
    assert launchable.text == "com.robler.warpcontrol.desktop"


def test_source_tarball_is_reproducible_and_sanitized(tmp_path: Path) -> None:
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"
    env = {**os.environ, "SOURCE_DATE_EPOCH": "1700000000"}

    for output in (first, second):
        subprocess.run(
            ["bash", "scripts/build-source-tarball.sh", str(output)],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

    assert hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(
        second.read_bytes()
    ).digest()
    assert int.from_bytes(first.read_bytes()[4:8], "little") == 0
    with tarfile.open(first, "r:gz") as archive:
        members = archive.getmembers()

    names = [member.name for member in members]
    assert names == sorted(names)
    assert "warp-control-2.0.0/pyproject.toml" in names
    assert "warp-control-2.0.0/packaging/rpm/warp-control.spec" in names
    assert all(member.uid == member.gid == 0 for member in members)
    assert all(member.mtime == 1700000000 for member in members)
    assert not any(
        excluded in name
        for name in names
        for excluded in ("/.git/", "/.venv/", "/build/", "/dist/")
    )


def test_source_manifest_carries_native_packaging_assets() -> None:
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    for line in (
        "include LICENSE README.md",
        "recursive-include data *",
        "recursive-include libexec *",
        "recursive-include packaging *",
        "recursive-include scripts *.sh",
    ):
        assert line in manifest
