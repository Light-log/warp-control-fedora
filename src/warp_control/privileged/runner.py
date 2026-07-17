"""Fail-closed process and progress primitives for root helpers."""

import fcntl
import json
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Sequence, TextIO

from warp_control.commands import CommandResult


FIXED_ENVIRONMENT = {
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "HOME": "/root",
}
ALLOWED_EXECUTABLES = frozenset(
    {
        "/usr/bin/apt-get",
        "/usr/bin/curl",
        "/usr/bin/dnf",
        "/usr/bin/gpg",
        "/usr/bin/systemctl",
    }
)
MAX_PROGRESS_MESSAGE = 2048
PROGRESS_STAGES = frozenset(
    {"validation", "epel", "repository", "metadata", "packages", "service", "complete"}
)
PROGRESS_STATUSES = frozenset({"running", "done", "error"})


class ConcurrentExecution(RuntimeError):
    pass


class PrivilegedCommandRunner:
    def __init__(self, run_callable: Callable = subprocess.run) -> None:
        self._run = run_callable

    def run(self, argv: Sequence[str], timeout: int = 300) -> CommandResult:
        if isinstance(argv, (str, bytes)) or not argv:
            raise ValueError("argv must be a non-empty sequence")
        command = tuple(argv)
        if not all(isinstance(value, str) and value and "\x00" not in value for value in command):
            raise ValueError("argv contains an invalid value")
        executable = command[0]
        if not executable.startswith("/") or executable not in ALLOWED_EXECUTABLES:
            raise ValueError("executable is not in the privileged allowlist")
        try:
            completed = self._run(
                list(command),
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=dict(FIXED_ENVIRONMENT),
                cwd="/",
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return CommandResult(False, "", type(error).__name__, 124)
        return CommandResult(
            completed.returncode == 0,
            completed.stdout or "",
            completed.stderr or "",
            completed.returncode,
        )


class JsonProgress:
    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def emit(self, stage: str, status: str, message: str) -> None:
        if stage not in PROGRESS_STAGES or status not in PROGRESS_STATUSES:
            raise ValueError("invalid progress event")
        if not isinstance(message, str) or not message or len(message.encode("utf-8")) > MAX_PROGRESS_MESSAGE:
            raise ValueError("invalid progress message")
        if any(ord(character) < 32 and character not in "\t" for character in message):
            raise ValueError("progress message contains control characters")
        line = json.dumps(
            {"stage": stage, "status": status, "message": message},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self._stream.write(line + "\n")
        self._stream.flush()


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    path = Path(path)
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    descriptor = os.open(
        path,
        os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
    )
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ConcurrentExecution("another privileged operation is active") from error
        yield
    finally:
        os.close(descriptor)
