import platform
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, Optional


_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")
_UNQUOTED_VALUE = re.compile(r"^[A-Za-z0-9._+:/@%-]*$")


class OsReleaseError(ValueError):
    pass


class Architecture(str, Enum):
    AMD64 = "amd64"
    ARM64 = "arm64"
    UNKNOWN = "unknown"


class Distribution(str, Enum):
    FEDORA = "fedora"
    UBUNTU = "ubuntu"
    DEBIAN = "debian"
    RHEL = "rhel"
    ARCH = "arch"
    MANJARO = "manjaro"
    ENDEAVOUROS = "endeavouros"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SystemInfo:
    distribution: Distribution
    version: Optional[str]
    codename: Optional[str]
    architecture: Architecture


def normalize_architecture(machine: str) -> Architecture:
    normalized = machine.strip().lower()
    if normalized in ("x86_64", "amd64"):
        return Architecture.AMD64
    if normalized in ("aarch64", "arm64"):
        return Architecture.ARM64
    return Architecture.UNKNOWN


def _decode_quoted(value: str, quote: str) -> str:
    if len(value) < 2 or value[-1] != quote:
        raise OsReleaseError("unterminated quoted value")
    body = value[1:-1]
    if quote == "'":
        if "'" in body:
            raise OsReleaseError("invalid single-quoted value")
        return body

    decoded = []
    position = 0
    while position < len(body):
        character = body[position]
        if character == "\\":
            position += 1
            if position >= len(body) or body[position] not in ('"', "\\", "$", "`"):
                raise OsReleaseError("unsupported escape in quoted value")
            decoded.append(body[position])
        elif character in ('"', "$", "`"):
            raise OsReleaseError("expansion syntax is not allowed")
        else:
            decoded.append(character)
        position += 1
    return "".join(decoded)


def _decode_value(value: str) -> str:
    if value.startswith(('"', "'")):
        return _decode_quoted(value, value[0])
    if not _UNQUOTED_VALUE.fullmatch(value):
        raise OsReleaseError("invalid unquoted value")
    return value


def parse_os_release(text: str) -> Dict[str, str]:
    """Parse os-release assignments as data, never as shell source."""

    result: Dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise OsReleaseError("os-release line is not an assignment")
        key, value = line.split("=", 1)
        if not _KEY.fullmatch(key) or key in result:
            raise OsReleaseError("invalid or duplicate os-release key")
        result[key] = _decode_value(value)
    return result


def _distribution(identifier: str) -> Distribution:
    identifiers = {
        "fedora": Distribution.FEDORA,
        "ubuntu": Distribution.UBUNTU,
        "debian": Distribution.DEBIAN,
        "rhel": Distribution.RHEL,
        "arch": Distribution.ARCH,
        "manjaro": Distribution.MANJARO,
        "endeavouros": Distribution.ENDEAVOUROS,
    }
    return identifiers.get(identifier.lower(), Distribution.UNKNOWN)


def detect_system(
    os_release_path: Path = Path("/etc/os-release"),
    machine: Optional[str] = None,
) -> SystemInfo:
    architecture = normalize_architecture(machine if machine is not None else platform.machine())
    try:
        values = parse_os_release(os_release_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, OsReleaseError):
        return SystemInfo(Distribution.UNKNOWN, None, None, architecture)

    identifier = values.get("ID", "")
    version = values.get("VERSION_ID")
    codename = values.get("VERSION_CODENAME") or values.get("UBUNTU_CODENAME")
    return SystemInfo(
        _distribution(identifier),
        version,
        codename.lower() if codename else None,
        architecture,
    )
