import logging

from warp_control.commands import CommandResult
from warp_control.services.diagnostics import (
    DiagnosticsService,
    configure_logging,
    default_log_path,
    redact,
)


class FakeRunner:
    def __init__(self):
        self.calls = []

    def run(self, argv, timeout=35):
        self.calls.append((argv, timeout))
        return CommandResult(True, "ok", "", 0)


def test_diagnostics_commands_use_fixed_argv_and_return_typed_results(tmp_path):
    runner = FakeRunner()
    log_path = tmp_path / "warp-control.log"
    service = DiagnosticsService(
        runner,
        log_path=log_path,
        pkexec="/test/pkexec",
        restart_helper="/test/restart-warp",
        connectivity_tool="/test/getent",
        opener="/test/gio",
    )

    assert service.restart_service().ok
    assert service.check_connectivity().ok
    assert service.open_log().ok

    assert runner.calls == [
        (["/test/pkexec", "/test/restart-warp"], 120),
        (["/test/getent", "ahosts", "cloudflare.com"], 15),
        (["/test/gio", "open", log_path.resolve().as_uri()], 15),
    ]
    assert log_path.exists()


def test_default_log_path_honors_only_absolute_xdg_state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert default_log_path() == tmp_path / "state/warp-control/warp-control.log"

    monkeypatch.setenv("XDG_STATE_HOME", "relative")
    assert default_log_path() == tmp_path / ".local/state/warp-control/warp-control.log"


def test_rotating_log_is_private_idempotent_and_redacts_secrets(tmp_path):
    path = tmp_path / "state" / "warp-control.log"
    logger = configure_logging(path, logger_name="warp_control.test")
    same = configure_logging(path, logger_name="warp_control.test")

    logger.info("token=topsecret Authorization: Bearer abc password=hunter2")
    for handler in logger.handlers:
        handler.flush()

    assert logger is same
    assert len(logger.handlers) == 1
    assert path.stat().st_mode & 0o777 == 0o600
    content = path.read_text(encoding="utf-8")
    assert "topsecret" not in content
    assert "hunter2" not in content
    assert "Bearer abc" not in content
    assert "[REDACTED]" in content
    logger.handlers.clear()


def test_redact_preserves_safe_diagnostics_and_masks_common_credentials():
    safe = "operation=refresh returncode=1"
    assert redact(safe) == safe
    assert "secret-value" not in redact("api_key: secret-value")
    assert logging.getLogger("warp_control").name == "warp_control"
