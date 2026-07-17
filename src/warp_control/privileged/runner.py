"""Fail-closed process and progress primitives for root helpers."""

import fcntl
import json
import os
import queue
import signal
import subprocess
import threading
import time
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
        "/usr/bin/apt-cache",
        "/usr/bin/curl",
        "/usr/bin/dnf",
        "/usr/bin/gpg",
        "/usr/bin/systemctl",
    }
)
MAX_PROGRESS_MESSAGE = 2048
MAX_COMMAND_OUTPUT = 256 * 1024
PROGRESS_STAGES = frozenset(
    {"validation", "epel", "repository", "metadata", "packages", "service", "complete"}
)
PROGRESS_STATUSES = frozenset({"running", "done", "error"})


class ConcurrentExecution(RuntimeError):
    pass


class PrivilegedCommandRunner:
    def __init__(
        self,
        process_factory: Callable = subprocess.Popen,
        clock: Callable[[], float] = time.monotonic,
        killpg: Callable[[int, int], None] = os.killpg,
        output_limit: int = MAX_COMMAND_OUTPUT,
    ) -> None:
        self._process_factory = process_factory
        self._clock = clock
        self._killpg = killpg
        self._output_limit = output_limit

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
            process = self._process_factory(
                list(command),
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                env=dict(FIXED_ENVIRONMENT),
                cwd="/",
                start_new_session=True,
            )
        except OSError as error:
            return CommandResult(False, "", type(error).__name__, 124)
        output_queue = queue.Queue(maxsize=32)
        stopped = threading.Event()
        threads = [
            threading.Thread(
                target=self._read_stream,
                args=(stream, name, output_queue, stopped),
                name=f"warp-control-{name}",
                daemon=True,
            )
            for stream, name in ((process.stdout, "stdout"), (process.stderr, "stderr"))
        ]
        for thread in threads:
            thread.start()
        stdout = bytearray()
        stderr = bytearray()
        deadline = self._clock() + timeout
        returncode = 124
        error_label = "command timed out"
        try:
            completed_streams = set()
            while len(completed_streams) < 2:
                remaining = deadline - self._clock()
                if remaining <= 0:
                    raise TimeoutError
                try:
                    name, chunk = output_queue.get(timeout=min(remaining, 0.1))
                except queue.Empty:
                    continue
                if chunk is None:
                    completed_streams.add(name)
                    continue
                target = stdout if name == "stdout" else stderr
                available = self._output_limit - len(stdout) - len(stderr)
                target.extend(chunk[: max(0, available)])
                if len(chunk) > available:
                    returncode = 125
                    error_label = "command output exceeded limit"
                    raise OverflowError
            remaining = max(0.001, deadline - self._clock())
            returncode = process.wait(timeout=remaining)
        except (TimeoutError, subprocess.TimeoutExpired, OverflowError):
            self._terminate_group(process)
            self._append_bounded(stderr, error_label.encode("ascii"), stdout)
        except Exception as error:
            returncode = 126
            self._terminate_group(process)
            self._append_bounded(
                stderr,
                type(error).__name__.encode("ascii", errors="replace"),
                stdout,
            )
        finally:
            stopped.set()
            for stream in (process.stdout, process.stderr):
                try:
                    stream.close()
                except (AttributeError, OSError):
                    pass
            for thread in threads:
                thread.join(timeout=0.2)
        return CommandResult(
            returncode == 0,
            bytes(stdout).decode("utf-8", errors="replace"),
            bytes(stderr).decode("utf-8", errors="replace"),
            returncode,
        )

    @staticmethod
    def _read_stream(stream, name: str, output_queue, stopped) -> None:
        try:
            while not stopped.is_set():
                chunk = stream.read(8192)
                if not chunk:
                    break
                while not stopped.is_set():
                    try:
                        output_queue.put((name, chunk), timeout=0.1)
                        break
                    except queue.Full:
                        continue
        finally:
            while not stopped.is_set():
                try:
                    output_queue.put((name, None), timeout=0.1)
                    break
                except queue.Full:
                    continue

    def _append_bounded(self, target: bytearray, value: bytes, other: bytearray) -> None:
        available = max(0, self._output_limit - len(target) - len(other))
        target.extend(value[:available])

    def _terminate_group(self, process) -> None:
        try:
            self._killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            try:
                process.kill()
            except (AttributeError, OSError):
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except (AttributeError, OSError):
                pass
            process.wait(timeout=5)


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
