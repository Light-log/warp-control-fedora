from pathlib import Path

import pytest

from warp_control.installers.detector import (
    Architecture,
    Distribution,
    OsReleaseError,
    detect_system,
    normalize_architecture,
    parse_os_release,
)


@pytest.mark.parametrize(
    ("machine", "expected"),
    [
        ("x86_64", Architecture.AMD64),
        ("amd64", Architecture.AMD64),
        ("aarch64", Architecture.ARM64),
        ("arm64", Architecture.ARM64),
        ("i686", Architecture.UNKNOWN),
        ("riscv64", Architecture.UNKNOWN),
    ],
)
def test_normalize_architecture_uses_a_closed_allowlist(machine, expected):
    assert normalize_architecture(machine) is expected


def test_parse_os_release_accepts_literal_quoted_values_only():
    parsed = parse_os_release(
        'NAME="Ubuntu Linux"\nID=ubuntu\nVERSION_ID="24.04"\n'
        'VERSION_CODENAME=noble\nID_LIKE="debian linux"\n'
    )

    assert parsed == {
        "NAME": "Ubuntu Linux",
        "ID": "ubuntu",
        "VERSION_ID": "24.04",
        "VERSION_CODENAME": "noble",
        "ID_LIKE": "debian linux",
    }


@pytest.mark.parametrize(
    "text",
    [
        "ID=ubuntu\nID=debian\n",
        "export ID=ubuntu\n",
        "ID=$(touch /tmp/unsafe)\n",
        "ID=`touch /tmp/unsafe`\n",
        "ID=ubuntu;echo unsafe\n",
        "BAD-KEY=value\n",
        'ID="unterminated\n',
        'ID="invalid"quote"\n',
        "ID=ubuntu\\ value\n",
    ],
)
def test_parse_os_release_rejects_ambiguous_or_executable_syntax(text):
    with pytest.raises(OsReleaseError):
        parse_os_release(text)


@pytest.mark.parametrize(
    ("identifier", "version", "codename", "expected"),
    [
        ("fedora", "43", None, Distribution.FEDORA),
        ("fedora", "44", None, Distribution.FEDORA),
        ("ubuntu", "22.04", "jammy", Distribution.UBUNTU),
        ("ubuntu", "24.04", "noble", Distribution.UBUNTU),
        ("ubuntu", "26.04", "resolute", Distribution.UBUNTU),
        ("debian", "12", "bookworm", Distribution.DEBIAN),
        ("debian", "13", "trixie", Distribution.DEBIAN),
        ("rhel", "9.7", None, Distribution.RHEL),
        ("rhel", "10", None, Distribution.RHEL),
        ("arch", None, None, Distribution.ARCH),
        ("manjaro", None, None, Distribution.MANJARO),
        ("endeavouros", None, None, Distribution.ENDEAVOUROS),
    ],
)
def test_detect_system_recognizes_only_named_distribution_families(
    tmp_path: Path, identifier, version, codename, expected
):
    lines = [f"ID={identifier}"]
    if version is not None:
        lines.append(f'VERSION_ID="{version}"')
    if codename is not None:
        lines.append(f"VERSION_CODENAME={codename}")
    path = tmp_path / "os-release"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    system = detect_system(path, machine="x86_64")

    assert system.distribution is expected
    assert system.architecture is Architecture.AMD64
    assert system.version == version
    assert system.codename == codename


def test_detect_system_does_not_promote_derivatives_to_official_support(tmp_path):
    path = tmp_path / "os-release"
    path.write_text(
        "ID=linuxmint\nID_LIKE=ubuntu\nVERSION_ID=22\n",
        encoding="utf-8",
    )

    system = detect_system(path, machine="x86_64")

    assert system.distribution is Distribution.UNKNOWN


def test_detect_system_fails_closed_when_os_release_is_missing(tmp_path):
    system = detect_system(tmp_path / "missing", machine="x86_64")

    assert system.distribution is Distribution.UNKNOWN
    assert system.architecture is Architecture.AMD64
