#!/usr/bin/env python3
"""Atomically pin the Arch package to a checked release source archive."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional, Sequence


REPO_ROOT = Path(__file__).resolve().parent.parent
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
PKGVER_RE = re.compile(r"^pkgver=[^\n]+$", re.MULTILINE)
SHA256SUMS_RE = re.compile(r"^sha256sums=\('[^'\n]*'\)$", re.MULTILINE)


def sha256(path: Path) -> str:
    """Return the SHA-256 digest of *path*, streaming 1 MiB at a time."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def _validate_release_fields(path: Path) -> Dict[str, str]:
    """Read exactly the two data fields in release.env without executing it."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError("could not read release.env: {0}".format(error)) from error

    fields: Dict[str, str] = {}
    for line in lines:
        match = re.fullmatch(r"(VERSION|SOURCE_DATE_EPOCH)=([^\r\n=]+)", line)
        if match is None or match.group(1) in fields:
            raise ValueError("release.env must contain one anchored VERSION and SOURCE_DATE_EPOCH")
        fields[match.group(1)] = match.group(2)
    if set(fields) != {"VERSION", "SOURCE_DATE_EPOCH"}:
        raise ValueError("release.env must contain one anchored VERSION and SOURCE_DATE_EPOCH")
    if VERSION_RE.fullmatch(fields["VERSION"]) is None:
        raise ValueError("release.env VERSION is not a semantic version")
    if re.fullmatch(r"[0-9]+", fields["SOURCE_DATE_EPOCH"]) is None:
        raise ValueError("release.env SOURCE_DATE_EPOCH is invalid")
    return fields


def update_pkgbuild(path: Path, *, version: str, digest: str) -> None:
    """Replace the single PKGBUILD version and checksum with validated values."""
    if VERSION_RE.fullmatch(version) is None:
        raise ValueError("version must be a semantic version")
    if DIGEST_RE.fullmatch(digest) is None:
        raise ValueError("digest must be a lowercase 64-character SHA-256")
    if path.is_symlink():
        raise ValueError("PKGBUILD must not be a symlink")

    try:
        original = path.read_text(encoding="utf-8")
        original_mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as error:
        raise ValueError("could not read PKGBUILD: {0}".format(error)) from error

    if len(PKGVER_RE.findall(original)) != 1:
        raise ValueError("PKGBUILD must contain exactly one anchored pkgver")
    if len(SHA256SUMS_RE.findall(original)) != 1:
        raise ValueError("PKGBUILD must contain exactly one anchored sha256sums")

    updated = PKGVER_RE.sub("pkgver={0}".format(version), original, count=1)
    updated = SHA256SUMS_RE.sub("sha256sums=('{0}')".format(digest), updated, count=1)

    descriptor, temporary_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".{0}.".format(path.name), suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            target.write(updated)
            target.flush()
            os.fchmod(target.fileno(), original_mode)
            os.fsync(target.fileno())
        os.replace(str(temporary), str(path))
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_descriptor = os.open(str(path.parent), directory_flags)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _usage() -> None:
    print("Usage: update-release-metadata.py --source-tarball PATH", file=sys.stderr)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Update repository-relative Arch metadata for one validated source tarball."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["--help"]:
        _usage()
        return 0
    if len(arguments) != 2 or arguments[0] != "--source-tarball":
        _usage()
        return 2

    tarball = Path(arguments[1])
    if not tarball.is_file():
        print("error: source tarball must be a regular file", file=sys.stderr)
        return 2

    try:
        release = _validate_release_fields(REPO_ROOT / "packaging" / "release.env")
        expected_name = "warp-control-{0}.tar.gz".format(release["VERSION"])
        if tarball.name != expected_name:
            raise ValueError("source tarball must be named {0}".format(expected_name))
        digest = sha256(tarball)
        update_pkgbuild(
            REPO_ROOT / "packaging" / "arch" / "PKGBUILD",
            version=release["VERSION"],
            digest=digest,
        )
    except (OSError, ValueError) as error:
        print("error: {0}".format(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
