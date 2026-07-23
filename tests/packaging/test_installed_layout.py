from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


ROOT = Path(__file__).parents[2]
SPEC = ROOT / "packaging/rpm/warp-control.spec"


def _clean_checkout(destination: Path) -> Path:
    checkout = destination / "checkout"
    checkout.mkdir()
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.split(b"\0")
    for encoded in tracked:
        if not encoded:
            continue
        relative = Path(os.fsdecode(encoded))
        target = checkout / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target, follow_symlinks=False)
    for relative in (
        "packaging/release.env",
        "scripts/update-release-metadata.py",
        "tests/packaging/test_release_metadata.py",
    ):
        source = ROOT / relative
        if source.exists():
            target = checkout / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Tests", "-c", "user.email=tests@example.invalid", "add", "."],
        cwd=checkout,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Tests",
            "-c",
            "user.email=tests@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=checkout,
        check=True,
    )
    return checkout


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
    for capability in (
        "/usr/bin/curl",
        "/usr/bin/dnf",
        "/usr/bin/gpg",
        "/usr/bin/systemctl",
    ):
        assert f"Requires:       {capability}" in spec
    for build_dependency in ("python3-gobject", "gtk3", "python3-idna"):
        assert f"BuildRequires:  {build_dependency}" in spec


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
    checkout = _clean_checkout(tmp_path)
    first = checkout / "dist/first.tar.gz"
    second = tmp_path / "second.tar.gz"
    env = {**os.environ, "SOURCE_DATE_EPOCH": "1700000000"}
    (checkout / "untracked-secret.txt").write_text("not for release", encoding="utf-8")

    subprocess.run(
        ["bash", "scripts/build-source-tarball.sh", str(first)],
        cwd=checkout,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    with (checkout / "packaging/arch/PKGBUILD").open("a", encoding="utf-8") as pkgbuild:
        pkgbuild.write("\n# Release checksum is intentionally outside its source archive.\n")
    subprocess.run(["git", "add", "packaging/arch/PKGBUILD"], cwd=checkout, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Tests",
            "-c",
            "user.email=tests@example.invalid",
            "commit",
            "-qm",
            "update checksum",
        ],
        cwd=checkout,
        check=True,
    )
    subprocess.run(
        ["bash", "scripts/build-source-tarball.sh", str(second)],
        cwd=checkout,
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
    assert "warp-control-2.0.0/packaging/arch/PKGBUILD" not in names
    assert "warp-control-2.0.0/untracked-secret.txt" not in names
    assert all(member.uid == member.gid == 0 for member in members)
    assert all(member.mtime == 1700000000 for member in members)
    assert not any(
        excluded in name
        for name in names
        for excluded in ("/.git/", "/.venv/", "/build/", "/dist/")
    )


def test_source_tarball_refuses_dirty_tracked_content(tmp_path: Path) -> None:
    checkout = _clean_checkout(tmp_path)
    output = tmp_path / "dirty.tar.gz"
    with (checkout / "README.md").open("a", encoding="utf-8") as readme:
        readme.write("\ncambio sin confirmar\n")

    result = subprocess.run(
        ["bash", "scripts/build-source-tarball.sh", str(output)],
        cwd=checkout,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "uncommitted changes" in result.stderr.lower()
    assert not output.exists()


def test_arch_checksum_matches_default_epoch_clean_source(tmp_path: Path) -> None:
    checkout = _clean_checkout(tmp_path)
    output = checkout / "dist/warp-control-2.0.0.tar.gz"

    subprocess.run(
        ["bash", "scripts/build-source-tarball.sh", str(output)],
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
    )

    pkgbuild = (checkout / "packaging/arch/PKGBUILD").read_text(encoding="utf-8")
    expected = re.search(r"^sha256sums=\('([0-9a-f]{64})'\)$", pkgbuild, re.MULTILINE)
    assert expected is not None
    assert hashlib.sha256(output.read_bytes()).hexdigest() == expected.group(1)


def test_source_tarball_uses_git_modes_when_filemode_is_ignored(tmp_path: Path) -> None:
    checkout = _clean_checkout(tmp_path)
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"
    environment = {**os.environ, "SOURCE_DATE_EPOCH": "1700000000"}

    subprocess.run(
        ["bash", "scripts/build-source-tarball.sh", str(first)],
        cwd=checkout,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    pyproject = checkout / "pyproject.toml"
    os.chmod(pyproject, 0o600)
    subprocess.run(["git", "config", "core.fileMode", "false"], cwd=checkout, check=True)
    subprocess.run(["git", "diff", "--quiet"], cwd=checkout, check=True)
    subprocess.run(
        ["bash", "scripts/build-source-tarball.sh", str(second)],
        cwd=checkout,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(
        second.read_bytes()
    ).digest()


def test_source_tarball_removes_temporary_source_tree_after_success(tmp_path: Path) -> None:
    checkout = _clean_checkout(tmp_path)
    output = tmp_path / "output" / "warp-control-2.0.0.tar.gz"

    subprocess.run(
        ["bash", "scripts/build-source-tarball.sh", str(output)],
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
    )

    assert output.exists()
    assert not list(output.parent.glob(".warp-control-source-tree.*"))


def test_source_tarball_cleans_archive_if_source_tree_creation_fails(tmp_path: Path) -> None:
    checkout = _clean_checkout(tmp_path)
    output = tmp_path / "output" / "warp-control-2.0.0.tar.gz"
    tools = tmp_path / "tools"
    tools.mkdir()
    real_mktemp = shutil.which("mktemp")
    assert real_mktemp is not None
    shim = tools / "mktemp"
    shim.write_text(
        "#!/usr/bin/bash\n"
        "if [[ $1 == -d ]]; then\n"
        "  exit 1\n"
        "fi\n"
        f'exec "{real_mktemp}" "$@"\n',
        encoding="utf-8",
    )
    os.chmod(shim, 0o755)
    environment = {**os.environ, "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}"}

    result = subprocess.run(
        ["bash", "scripts/build-source-tarball.sh", str(output)],
        cwd=checkout,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert not output.exists()
    assert not list(output.parent.glob(".warp-control-source.*.tar.gz"))


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


def test_packaging_text_files_end_with_exactly_one_newline() -> None:
    for relative in (
        "MANIFEST.in",
        "data/com.robler.warpcontrol.metainfo.xml",
        "data/icons/com.robler.warpcontrol.svg",
        "packaging/rpm/warp-control.spec",
        "scripts/build-source-tarball.sh",
    ):
        content = (ROOT / relative).read_bytes()
        assert content.endswith(b"\n"), relative
        assert not content.endswith(b"\n\n"), relative
