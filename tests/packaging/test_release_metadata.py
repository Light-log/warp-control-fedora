"""Behavioral tests for release checksum metadata updates."""

from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "update-release-metadata.py"
SPEC = importlib.util.spec_from_file_location("update_release_metadata", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def _pkgbuild(path: Path, *, version: str = "1.0.0", digest: str = "0" * 64) -> None:
    path.write_text(
        "pkgname=warp-control\n"
        f"pkgver={version}\n"
        f"sha256sums=('{digest}')\n",
        encoding="utf-8",
    )


def _release_repo(path: Path) -> tuple[Path, Path]:
    (path / "packaging" / "arch").mkdir(parents=True)
    (path / "packaging" / "release.env").write_text(
        "VERSION=2.0.0\nSOURCE_DATE_EPOCH=1784678400\n", encoding="utf-8"
    )
    pkgbuild = path / "packaging" / "arch" / "PKGBUILD"
    _pkgbuild(pkgbuild)
    return path, pkgbuild


def test_sha256_hashes_large_files(tmp_path: Path) -> None:
    path = tmp_path / "fixture"
    payload = b"a" * (1024 * 1024) + b"b" * (1024 * 1024) + b"c"
    path.write_bytes(payload)
    assert module.sha256(path) == hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize("version", ["2", "2.0", "v2.0.0", "2.0.0-rc1"])
def test_update_pkgbuild_rejects_non_semantic_version(tmp_path: Path, version: str) -> None:
    pkgbuild = tmp_path / "PKGBUILD"
    _pkgbuild(pkgbuild)
    before = pkgbuild.read_bytes()

    with pytest.raises(ValueError, match="semantic version"):
        module.update_pkgbuild(pkgbuild, version=version, digest="a" * 64)

    assert pkgbuild.read_bytes() == before


@pytest.mark.parametrize("digest", ["A" * 64, "a" * 63, "not-a-digest"])
def test_update_pkgbuild_rejects_non_lowercase_digest(tmp_path: Path, digest: str) -> None:
    pkgbuild = tmp_path / "PKGBUILD"
    _pkgbuild(pkgbuild)
    before = pkgbuild.read_bytes()

    with pytest.raises(ValueError, match="digest"):
        module.update_pkgbuild(pkgbuild, version="2.0.0", digest=digest)

    assert pkgbuild.read_bytes() == before


@pytest.mark.parametrize(
    "content, message",
    [
        ("sha256sums=('0')\n", "pkgver"),
        ("pkgver=1.0.0\n", "sha256sums"),
        ("pkgver=1.0.0\npkgver=1.0.1\nsha256sums=('0')\n", "pkgver"),
        ("pkgver=1.0.0\nsha256sums=('0')\nsha256sums=('1')\n", "sha256sums"),
    ],
)
def test_update_pkgbuild_requires_one_anchored_field(
    tmp_path: Path, content: str, message: str
) -> None:
    pkgbuild = tmp_path / "PKGBUILD"
    pkgbuild.write_text(content, encoding="utf-8")
    before = pkgbuild.read_bytes()

    with pytest.raises(ValueError, match=message):
        module.update_pkgbuild(pkgbuild, version="2.0.0", digest="a" * 64)

    assert pkgbuild.read_bytes() == before


def test_update_pkgbuild_refuses_symlink_and_preserves_target(tmp_path: Path) -> None:
    target = tmp_path / "target"
    _pkgbuild(target)
    link = tmp_path / "PKGBUILD"
    link.symlink_to(target)
    before = target.read_bytes()

    with pytest.raises(ValueError, match="symlink"):
        module.update_pkgbuild(link, version="2.0.0", digest="a" * 64)

    assert target.read_bytes() == before


def test_update_pkgbuild_replaces_fields_and_preserves_mode(tmp_path: Path) -> None:
    pkgbuild = tmp_path / "PKGBUILD"
    _pkgbuild(pkgbuild)
    os.chmod(pkgbuild, 0o754)

    module.update_pkgbuild(pkgbuild, version="2.0.0", digest="a" * 64)

    assert pkgbuild.read_text(encoding="utf-8") == (
        "pkgname=warp-control\npkgver=2.0.0\nsha256sums=('" + "a" * 64 + "')\n"
    )
    assert pkgbuild.stat().st_mode & 0o777 == 0o754


def test_main_uses_repo_metadata_and_refuses_wrong_release_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, pkgbuild = _release_repo(tmp_path / "repo")
    tarball = tmp_path / "warp-control-9.0.0.tar.gz"
    tarball.write_bytes(b"release")
    before = pkgbuild.read_bytes()
    monkeypatch.setattr(module, "REPO_ROOT", repo)

    assert module.main(["--source-tarball", str(tarball)]) == 2

    assert pkgbuild.read_bytes() == before


def test_main_updates_repo_relative_pkgbuild(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, pkgbuild = _release_repo(tmp_path / "repo")
    tarball = tmp_path / "warp-control-2.0.0.tar.gz"
    tarball.write_bytes(b"release")
    monkeypatch.setattr(module, "REPO_ROOT", repo)

    assert module.main(["--source-tarball", str(tarball)]) == 0

    assert "pkgver=2.0.0" in pkgbuild.read_text(encoding="utf-8")
    assert module.sha256(tarball) in pkgbuild.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "argv",
    [[], ["--source-tarball"], ["--unexpected"], ["--source-tarball", "a", "extra"]],
)
def test_main_returns_two_for_invalid_cli(argv: list[str]) -> None:
    assert module.main(argv) == 2
