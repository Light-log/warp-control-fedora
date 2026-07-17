import json

import pytest

from warp_control.installers import installation_plan
from warp_control.installers.detector import Architecture, Distribution, SystemInfo
from warp_control.models import OperationResult, RegistrationState, RegistrationStatus
from warp_control.ui.install_dialog import (
    InstallDecision,
    InstallerProcess,
    InstallPresenter,
    ProgressProtocolError,
    RegistrationCoordinator,
    RetryCoordinator,
    RetryDecision,
    RetryStage,
    build_pkexec_argv,
    parse_progress_line,
)


def system(distribution, version, codename=None):
    return SystemInfo(distribution, version, codename, Architecture.AMD64)


def test_supported_flow_requires_two_explicit_confirmations_and_mentions_epel():
    info = system(Distribution.RHEL, "9")
    presenter = InstallPresenter(info, installation_plan(info))

    first = presenter.choose(InstallDecision.INSTALL_NOW)
    assert first.needs_confirmation is True
    assert "EPEL" in first.summary
    assert presenter.can_launch is False
    presenter.confirm_changes(True)
    assert presenter.can_launch is True


def test_second_confirmation_cannot_be_bypassed():
    info = system(Distribution.FEDORA, "44")
    presenter = InstallPresenter(info, installation_plan(info))
    presenter.confirm_changes(True)
    assert presenter.can_launch is False


def test_cancel_or_decline_enters_limited_mode():
    info = system(Distribution.FEDORA, "44")
    presenter = InstallPresenter(info, installation_plan(info))
    state = presenter.choose(InstallDecision.NOT_NOW)
    assert state.limited_mode is True
    assert presenter.can_launch is False


def test_arch_only_offers_instructions_and_never_pkexec():
    info = system(Distribution.ARCH, None)
    presenter = InstallPresenter(info, installation_plan(info))
    state = presenter.choose(InstallDecision.INSTALL_NOW)
    assert state.open_instructions is True
    assert state.needs_confirmation is False
    assert presenter.can_launch is False


def test_pkexec_command_is_exact_and_argument_free():
    assert build_pkexec_argv() == (
        "/usr/bin/pkexec",
        "/usr/libexec/warp-control/install-warp",
    )


def test_installer_process_spawns_exact_pkexec_without_stdin_or_shell():
    calls = []

    class Output:
        lines = [
            json.dumps({"stage": "complete", "status": "done", "message": "Listo"}) + "\n",
            "",
        ]

        def readline(self, _limit):
            return self.lines.pop(0)

    class Process:
        stdout = Output()

        def wait(self, timeout):
            assert timeout == 5
            return 0

        def poll(self):
            return 0

    def fake_popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return Process()

    assert list(InstallerProcess(fake_popen).events())[0].message == "Listo"
    argv, options = calls[0]
    assert argv == ["/usr/bin/pkexec", "/usr/libexec/warp-control/install-warp"]
    assert options["shell"] is False
    assert options["stdin"] is not None


def test_progress_parser_accepts_only_bounded_jsonl_schema():
    line = json.dumps({"stage": "packages", "status": "done", "message": "Listo"})
    assert parse_progress_line(line).stage == "packages"
    for invalid in (
        "not json",
        json.dumps({"stage": "packages", "status": "done"}),
        json.dumps({"stage": "evil", "status": "done", "message": "x"}),
        json.dumps({"stage": "packages", "status": "done", "message": "x", "extra": 1}),
        "x" * 9000,
    ):
        with pytest.raises(ProgressProtocolError):
            parse_progress_line(invalid)


def test_registration_requires_explicit_terms_acceptance():
    info = system(Distribution.DEBIAN, "12", "bookworm")
    presenter = InstallPresenter(info, installation_plan(info))
    assert presenter.registration_argv(False) is None
    assert presenter.limited_mode is True
    assert presenter.registration_argv(True) == (
        "/usr/bin/warp-cli",
        "--accept-tos",
        "registration",
        "new",
    )


def test_registration_coordinator_checks_existing_cli_and_registers_only_after_terms():
    calls = []

    class Warp:
        def registration_status(self):
            calls.append("status")
            return RegistrationStatus(False, "missing", 1, RegistrationState.UNREGISTERED)

        def register(self):
            calls.append("register")
            return OperationResult(True, "", 0)

    class Tasks:
        def submit(self, worker, success, failure):
            try:
                success(worker())
            except Exception as error:
                failure(error)

    completed = []
    limited = []
    retries = []
    flow = RegistrationCoordinator(
        warp=Warp(),
        tasks=Tasks(),
        request_terms=lambda: True,
        on_complete=lambda: completed.append(True),
        on_limited=lambda message: limited.append(message),
        on_retry=lambda callback, message: retries.append((callback, message)),
    )
    assert flow.start() is True
    assert calls == ["status", "register"]
    assert completed == [True]
    assert limited == []
    assert retries == []


def test_registration_failure_enters_limited_mode_and_exposes_real_retry():
    class Warp:
        def registration_status(self):
            return RegistrationStatus(False, "missing", 1, RegistrationState.UNREGISTERED)

        def register(self):
            return OperationResult(False, "failed", 7)

    class Tasks:
        def submit(self, worker, success, failure):
            success(worker())

    retries = []
    limited = []
    flow = RegistrationCoordinator(
        warp=Warp(), tasks=Tasks(), request_terms=lambda: True,
        on_complete=lambda: None,
        on_limited=lambda message: limited.append(message),
        on_retry=lambda callback, message: retries.append((callback, message)),
    )
    flow.start()
    assert limited
    assert len(retries) == 1
    assert retries[0][0] == flow.start


@pytest.mark.parametrize("stage", list(RetryStage))
def test_stage_retry_is_deferred_once_without_nested_or_duplicate_work(stage):
    deferred = []
    retries = []
    decisions = []
    recovery = RetryCoordinator(
        request_decision=lambda received: decisions.append(received) or RetryDecision.RETRY,
        defer=deferred.append,
        on_limited=lambda: pytest.fail("unexpected limited mode"),
    )

    assert recovery.recover(stage, lambda: retries.append(stage)) is True
    assert recovery.recover(stage, lambda: retries.append("duplicate")) is False
    assert decisions == [stage]
    assert retries == []
    assert len(deferred) == 1

    deferred.pop()()
    assert retries == [stage]
    assert recovery.retry_scheduled is False


def test_retry_decline_enters_limited_mode_without_scheduling_work():
    limited = []
    deferred = []
    recovery = RetryCoordinator(
        request_decision=lambda _stage: RetryDecision.LIMITED,
        defer=deferred.append,
        on_limited=lambda: limited.append(True),
    )
    assert recovery.recover(RetryStage.INSTALLATION, lambda: pytest.fail("retried")) is False
    assert limited == [True]
    assert deferred == []
