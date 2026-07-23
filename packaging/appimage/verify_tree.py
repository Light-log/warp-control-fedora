#!/usr/bin/env python3
"""Verify that an extracted AppImage exactly matches its staged AppDir."""

from __future__ import annotations

import hashlib
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Sequence


class VerificationError(ValueError):
    """The extracted tree is not the staged permitted set."""


@dataclass(frozen=True)
class Entry:
    kind: str
    mode: int
    digest: Optional[str] = None
    target: Optional[str] = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _validate_symlink(relative: Path, target: str) -> None:
    if not target or target.startswith("/") or any(c in target for c in "\r\n"):
        raise VerificationError(f"absolute or escaping symlink: {relative}")

    depth = len(relative.parent.parts)
    for component in target.split("/"):
        if component in ("", "."):
            continue
        if component == "..":
            if depth == 0:
                raise VerificationError(f"absolute or escaping symlink: {relative}")
            depth -= 1
        else:
            depth += 1


def _scan(root: Path) -> Dict[str, Entry]:
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise VerificationError(f"tree root must be an absolute real directory: {root}")

    entries: Dict[str, Entry] = {}

    def visit(directory: Path, relative_directory: Path) -> None:
        try:
            children = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as error:
            raise VerificationError(f"cannot scan tree: {relative_directory}") from error
        for child in children:
            relative = relative_directory / child.name
            key = relative.as_posix()
            metadata = child.stat(follow_symlinks=False)
            mode = stat.S_IMODE(metadata.st_mode)
            path = Path(child.path)
            if stat.S_ISREG(metadata.st_mode):
                entries[key] = Entry("file", mode, digest=_sha256(path))
            elif stat.S_ISDIR(metadata.st_mode):
                entries[key] = Entry("directory", mode)
                visit(path, relative)
            elif stat.S_ISLNK(metadata.st_mode):
                target = os.readlink(path)
                _validate_symlink(relative, target)
                entries[key] = Entry("symlink", mode, target=target)
            else:
                raise VerificationError(f"unsupported entry type: {relative}")

    visit(root, Path())
    return entries


def verify_trees(staged: Path, extracted: Path) -> None:
    permitted = _scan(staged)
    observed = _scan(extracted)
    missing = sorted(permitted.keys() - observed.keys())
    unexpected = sorted(observed.keys() - permitted.keys())
    if missing or unexpected:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unexpected:
            details.append("unexpected: " + ", ".join(unexpected))
        raise VerificationError("; ".join(details))

    for relative in sorted(permitted):
        expected = permitted[relative]
        actual = observed[relative]
        if expected.kind != actual.kind:
            raise VerificationError(f"entry type changed: {relative}")
        if expected.mode != actual.mode:
            raise VerificationError(f"entry mode changed: {relative}")
        if expected.kind == "file" and expected.digest != actual.digest:
            raise VerificationError(f"file content changed: {relative}")
        if expected.kind == "symlink" and expected.target != actual.target:
            raise VerificationError(f"symlink target changed: {relative}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 2:
        print("Usage: verify_tree.py STAGED_APPDIR EXTRACTED_APPDIR", file=sys.stderr)
        return 2
    try:
        verify_trees(Path(arguments[0]), Path(arguments[1]))
    except (OSError, VerificationError) as error:
        print(f"AppImage tree verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
