import os
import subprocess
from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Sequence, Union


_MISSING_EXECUTABLE = 127
_CANNOT_EXECUTE = 126
_TIMED_OUT = 124
_Output = Optional[Union[str, bytes]]


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    stdout: str
    stderr: str
    returncode: int

    @property
    def combined_output(self) -> str:
        if not self.stdout:
            return self.stderr
        if not self.stderr:
            return self.stdout
        separator = "" if self.stdout.endswith("\n") else "\n"
        return f"{self.stdout}{separator}{self.stderr}"


def _text(value: _Output) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


class CommandRunner:
    def __init__(self, run_callable: Callable = subprocess.run) -> None:
        self._run = run_callable

    def run(self, argv: Sequence[str], timeout: int = 35) -> CommandResult:
        if isinstance(argv, (str, bytes)) or not argv:
            raise ValueError("argv must be a non-empty sequence, not a string")

        command = list(argv)
        environment: Mapping[str, str] = {
            **os.environ,
            "LC_ALL": "C",
            "LANG": "C",
        }
        try:
            completed = self._run(
                command,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=environment,
            )
        except FileNotFoundError as error:
            return CommandResult(False, "", str(error), _MISSING_EXECUTABLE)
        except OSError as error:
            return CommandResult(False, "", str(error), _CANNOT_EXECUTE)
        except subprocess.TimeoutExpired as error:
            return CommandResult(
                False,
                _text(error.output),
                _text(error.stderr),
                _TIMED_OUT,
            )

        return CommandResult(
            completed.returncode == 0,
            completed.stdout,
            completed.stderr,
            completed.returncode,
        )
