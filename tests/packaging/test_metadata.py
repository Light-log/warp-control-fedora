from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).parents[2]
CONTROL = ROOT / "debian/control"
INSTALL = ROOT / "debian/warp-control.install"
PKGBUILD = ROOT / "packaging/arch/PKGBUILD"
RELEASE_ENV = ROOT / "packaging/release.env"


def _paragraphs(text: str) -> list[dict[str, str]]:
    paragraphs: list[dict[str, str]] = []
    for block in text.strip().split("\n\n"):
        fields: dict[str, str] = {}
        current = ""
        for line in block.splitlines():
            if line.startswith((" ", "\t")):
                fields[current] += "\n" + line[1:]
                continue
            current, value = line.split(":", 1)
            fields[current] = value.strip()
        paragraphs.append(fields)
    return paragraphs


def _shell_array(text: str, name: str) -> set[str]:
    match = re.search(rf"^{name}=\((.*?)\)$", text, flags=re.MULTILINE | re.DOTALL)
    assert match is not None, name
    return set(re.findall(r"['\"]([^'\"]+)['\"]", match.group(1)))


def test_debian_control_is_architecture_independent_and_native() -> None:
    source, binary = _paragraphs(CONTROL.read_text(encoding="utf-8"))

    assert source["Source"] == "warp-control"
    assert source["Homepage"] == "https://github.com/Light-log/warp-control-fedora"
    assert binary["Package"] == "warp-control"
    assert binary["Architecture"] == "all"
    build_depends = source["Build-Depends"]
    for dependency in (
        "debhelper-compat (= 13)",
        "dh-sequence-python3",
        "pybuild-plugin-pyproject",
        "python3-all",
        "python3-setuptools",
        "python3-wheel",
    ):
        assert dependency in build_depends

    depends = binary["Depends"]
    for dependency in (
        "${python3:Depends}",
        "${misc:Depends}",
        "python3-gi",
        "gir1.2-gtk-3.0",
        "gir1.2-ayatanaappindicator3-0.1",
        "python3-idna",
        "pkexec",
        "polkitd",
        "apt",
        "curl",
        "gnupg",
        "systemd",
    ):
        assert dependency in depends
    assert "policykit-1" not in depends


def test_debian_rules_uses_pybuild_pyproject() -> None:
    rules = (ROOT / "debian/rules").read_text(encoding="utf-8")

    assert rules.startswith("#!/usr/bin/make -f\n")
    assert "PYBUILD_SYSTEM=pyproject" in rules
    assert "dh $@ --with python3 --buildsystem=pybuild" in rules
    assert '-m "not ui"' in rules


def test_debian_install_manifest_is_explicit() -> None:
    entries = set(INSTALL.read_text(encoding="utf-8").splitlines())

    assert entries == {
        "data/com.robler.warpcontrol.desktop usr/share/applications/",
        "data/com.robler.warpcontrol.metainfo.xml usr/share/metainfo/",
        "data/icons/com.robler.warpcontrol.svg usr/share/icons/hicolor/scalable/apps/",
        "data/com.robler.warpcontrol.policy usr/share/polkit-1/actions/",
        "libexec/warp-control/install-warp usr/libexec/warp-control/",
        "libexec/warp-control/restart-warp usr/libexec/warp-control/",
    }


def test_arch_package_is_application_only_and_architecture_independent() -> None:
    pkgbuild = PKGBUILD.read_text(encoding="utf-8")

    assert "arch=('any')" in pkgbuild
    assert "url='https://github.com/Light-log/warp-control-fedora'" in pkgbuild
    assert "license=('MIT')" in pkgbuild
    assert _shell_array(pkgbuild, "depends") == {
        "python",
        "python-gobject",
        "gtk3",
        "libayatana-appindicator",
        "python-idna",
    }
    assert "warp-cli" in pkgbuild
    assert "experimental" in pkgbuild.lower()
    assert "optdepends=" not in pkgbuild
    assert "usr/share/applications" in pkgbuild
    assert "usr/share/metainfo" in pkgbuild
    assert "usr/share/icons/hicolor/scalable/apps" in pkgbuild
    assert "usr/libexec" not in pkgbuild
    assert "polkit-1" not in pkgbuild


def test_arch_source_is_a_tarball_release() -> None:
    pkgbuild = PKGBUILD.read_text(encoding="utf-8")
    sources = _shell_array(pkgbuild, "source")
    checksums = _shell_array(pkgbuild, "sha256sums")
    makedepends = _shell_array(pkgbuild, "makedepends")

    assert "source_commit=" not in pkgbuild
    assert "git+" not in pkgbuild
    assert len(sources) == 1
    source = next(iter(sources))
    assert "releases/download/v" in source
    assert "$pkgname-$pkgver.tar.gz" in source
    assert len(checksums) == 1
    checksum = next(iter(checksums))
    assert re.fullmatch(r"[a-f0-9]{64}", checksum), f"Expected lowercase 64-char sha256, got {checksum}"
    assert "SKIP" not in checksums
    assert "git" not in makedepends
    assert 'cd "$srcdir/$pkgname-$pkgver"' in pkgbuild or 'cd "$srcdir/warp-control-$pkgver"' in pkgbuild


def test_release_contract_has_one_valid_version_and_epoch() -> None:
    assert RELEASE_ENV.read_text(encoding="utf-8").splitlines() == [
        "VERSION=2.0.0",
        "SOURCE_DATE_EPOCH=1784678400",
    ]


def test_native_packages_never_depend_on_or_install_cloudflare_warp() -> None:
    control = CONTROL.read_text(encoding="utf-8").lower()
    pkgbuild = PKGBUILD.read_text(encoding="utf-8").lower()

    assert "cloudflare-warp" not in control
    assert "cloudflare-warp" not in pkgbuild
    assert not any(
        (ROOT / "debian" / name).exists()
        for name in ("postinst", "preinst", "postrm", "prerm")
    )


def test_debian_metadata_files_are_complete() -> None:
    changelog = (ROOT / "debian/changelog").read_text(encoding="utf-8")
    copyright_text = (ROOT / "debian/copyright").read_text(encoding="utf-8")

    assert changelog.startswith("warp-control (2.0.0-1) unstable; urgency=medium\n")
    assert "Fri, 17 Jul 2026" in changelog
    assert "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/" in copyright_text
    assert "License: MIT" in copyright_text
    assert (ROOT / "debian/source/format").read_text(encoding="utf-8") == "3.0 (quilt)\n"


def test_packaging_metadata_ends_with_one_newline() -> None:
    for relative in (
        "debian/control",
        "debian/rules",
        "debian/changelog",
        "debian/copyright",
        "debian/source/format",
        "debian/warp-control.install",
        "packaging/arch/PKGBUILD",
    ):
        content = (ROOT / relative).read_bytes()
        assert content.endswith(b"\n"), relative
        assert not content.endswith(b"\n\n"), relative
