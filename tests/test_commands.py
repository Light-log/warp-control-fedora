import subprocess

import pytest

from warp_control.commands import CommandResult, CommandRunner


def test_command_result_is_immutable_and_combines_separate_output():
    result = CommandResult(
        ok=False,
        stdout="standard output\n",
        stderr="standard error\n",
        returncode=2,
    )

    assert result.combined_output == "standard output\nstandard error\n"
    with pytest.raises((AttributeError, TypeError)):
        result.ok = True


def test_runner_passes_exact_safe_subprocess_arguments(monkeypatch):
    monkeypatch.setenv("WARP_CONTROL_TEST_ENV", "preserved")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "done", "")

    result = CommandRunner(run_callable=fake_run).run(
        ("warp-cli", "status"), timeout=7
    )

    assert result == CommandResult(True, "done", "", 0)
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == ["warp-cli", "status"]
    assert kwargs["shell"] is False
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["timeout"] == 7
    assert kwargs["env"]["LC_ALL"] == "C"
    assert kwargs["env"]["LANG"] == "C"
    assert kwargs["env"]["WARP_CONTROL_TEST_ENV"] == "preserved"


@pytest.mark.parametrize("argv", ["warp-cli status", b"warp-cli", [], ()])
def test_runner_rejects_string_bytes_and_empty_commands(argv):
    with pytest.raises(ValueError):
        CommandRunner().run(argv)


def test_runner_converts_missing_executable_to_failed_result():
    def missing(argv, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", argv[0])

    result = CommandRunner(run_callable=missing).run(["missing-command"])

    assert result.ok is False
    assert result.stdout == ""
    assert "missing-command" in result.stderr
    assert result.returncode == 127


def test_runner_converts_other_execution_os_errors_to_failed_result():
    def denied(argv, **kwargs):
        raise PermissionError(13, "Permission denied", argv[0])

    result = CommandRunner(run_callable=denied).run(["non-executable"])

    assert result.ok is False
    assert result.stdout == ""
    assert "non-executable" in result.stderr
    assert result.returncode == 126


def test_runner_converts_timeout_and_preserves_partial_output():
    def times_out(argv, **kwargs):
        raise subprocess.TimeoutExpired(
            argv,
            kwargs["timeout"],
            output="partial stdout",
            stderr="partial stderr",
        )

    result = CommandRunner(run_callable=times_out).run(["slow"], timeout=3)

    assert result == CommandResult(
        ok=False,
        stdout="partial stdout",
        stderr="partial stderr",
        returncode=124,
    )


def test_runner_decodes_byte_output_from_timeout():
    def times_out(argv, **kwargs):
        raise subprocess.TimeoutExpired(
            argv, kwargs["timeout"], output=b"partial", stderr=b"late"
        )

    result = CommandRunner(run_callable=times_out).run(["slow"])

    assert result.stdout == "partial"
    assert result.stderr == "late"


def test_runner_returns_nonzero_result_without_throwing():
    def fails(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 23, "output", "problem")

    result = CommandRunner(run_callable=fails).run(["warp-cli", "status"])

    assert result == CommandResult(False, "output", "problem", 23)


def test_runner_preserves_successful_stdout_and_stderr():
    def succeeds(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, "output", "warning")

    result = CommandRunner(run_callable=succeeds).run(["warp-cli", "status"])

    assert result == CommandResult(True, "output", "warning", 0)
