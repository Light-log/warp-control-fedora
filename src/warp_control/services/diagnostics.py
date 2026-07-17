"""Typed diagnostic actions and privacy-conscious rotating application logs."""

import logging
import os
import re
import stat
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Union

from warp_control.commands import CommandRunner
from warp_control.models import OperationResult


_CREDENTIALS = (
    re.compile(
        r"(?i)\b(authorization\s*:\s*bearer)\s+[^\s,;]+"
    ),
    re.compile(
        r"(?i)\b(token|password|passwd|api[_-]?key|secret)"
        r"(\s*[:=]\s*)[^\s,;]+"
    ),
)


def default_log_path() -> Path:
    configured = os.environ.get("XDG_STATE_HOME")
    base = Path(configured) if configured and Path(configured).is_absolute() else None
    if base is None:
        base = Path.home() / ".local" / "state"
    return base / "warp-control" / "warp-control.log"


def redact(message: object) -> str:
    safe = str(message)
    safe = _CREDENTIALS[0].sub(r"\1 [REDACTED]", safe)
    safe = _CREDENTIALS[1].sub(r"\1\2[REDACTED]", safe)
    return safe


class _RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def configure_logging(
    path: Optional[Union[Path, str]] = None,
    *,
    logger_name: str = "warp_control",
) -> logging.Logger:
    log_path = Path(path) if path is not None else default_log_path()
    log_path = log_path.expanduser()
    if not log_path.is_absolute():
        raise ValueError("log path must be absolute")
    log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if log_path.is_symlink():
        raise OSError(f"refusing symlink log target: {log_path}")

    logger = logging.getLogger(logger_name)
    resolved = log_path.resolve(strict=False)
    for handler in logger.handlers:
        if getattr(handler, "_warp_control_path", None) == resolved:
            return logger

    handler = RotatingFileHandler(
        log_path, maxBytes=512 * 1024, backupCount=3, encoding="utf-8"
    )
    os.chmod(log_path, stat.S_IRUSR | stat.S_IWUSR)
    handler._warp_control_path = resolved  # type: ignore[attr-defined]
    handler.setFormatter(
        _RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


class DiagnosticsService:
    """Execute the three fixed advanced-tool actions exposed by the UI."""

    def __init__(
        self,
        runner: CommandRunner,
        *,
        log_path: Optional[Union[Path, str]] = None,
        pkexec: str = "/usr/bin/pkexec",
        restart_helper: str = "/usr/libexec/warp-control/restart-warp",
        connectivity_tool: str = "/usr/bin/getent",
        opener: str = "/usr/bin/gio",
    ) -> None:
        self._runner = runner
        self.log_path = Path(log_path) if log_path is not None else default_log_path()
        self._pkexec = pkexec
        self._restart_helper = restart_helper
        self._connectivity_tool = connectivity_tool
        self._opener = opener

    @staticmethod
    def _typed(command) -> OperationResult:
        return OperationResult(
            command.ok, command.combined_output, command.returncode
        )

    def restart_service(self) -> OperationResult:
        return self._typed(
            self._runner.run(
                [self._pkexec, self._restart_helper], timeout=120
            )
        )

    def check_connectivity(self) -> OperationResult:
        return self._typed(
            self._runner.run(
                [self._connectivity_tool, "ahosts", "cloudflare.com"],
                timeout=15,
            )
        )

    def open_log(self) -> OperationResult:
        self.log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.log_path.is_symlink():
            return OperationResult(
                False, f"refusing symlink log target: {self.log_path}", 126
            )
        self.log_path.touch(mode=0o600, exist_ok=True)
        os.chmod(self.log_path, 0o600)
        uri = self.log_path.resolve().as_uri()
        return self._typed(
            self._runner.run([self._opener, "open", uri], timeout=15)
        )
