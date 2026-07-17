import json
import threading

import pytest

from warp_control.installers import installation_plan
from warp_control.installers.detector import Architecture, Distribution, SystemInfo
from warp_control.models import OperationResult, RegistrationState, RegistrationStatus
from warp_control.privileged.helper import (
    INSTALL_IDLE_GRACE,
    MAX_INSTALL_TOTAL_TIMEOUT,
    MAX_STAGE_TIMEOUT,
)
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
    assert options["start_new_session"] is True


@pytest.mark.parametrize(
    "lines",
    [
        [""],
        [json.dumps({"stage": "packages", "status": "done", "message": "Paquete"}) + "\n", ""],
        [
            json.dumps({"stage": "complete", "status": "done", "message": "Listo"}) + "\n",
            json.dumps({"stage": "service", "status": "done", "message": "Tarde"}) + "\n",
            "",
        ],
    ],
)
def test_installer_protocol_rejects_empty_truncated_or_post_terminal_output(lines):
    class Output:
        def readline(self, _limit):
            return lines.pop(0)

        def close(self):
            return None

    class Process:
        stdout = Output()
        killed = False
        waits = 0

        def wait(self, timeout):
            self.waits += 1
            return 0

        def poll(self):
            return None if not self.killed else -9

        def kill(self):
            self.killed = True

    process = Process()
    with pytest.raises(ProgressProtocolError):
        list(InstallerProcess(lambda *args, **kwargs: process).events())
    assert process.killed is True
    assert process.waits >= 1


@pytest.mark.parametrize(
    "timeouts",
    [
        {"overall_timeout": 0, "idle_timeout": 100},
        {"overall_timeout": 100, "idle_timeout": 0},
    ],
)
def test_installer_progress_timeouts_kill_and_wait(timeouts):
    class BlockingOutput:
        def readline(self, _limit):
            threading.Event().wait(0.5)
            return b""

        def close(self):
            return None

    class Process:
        stdout = BlockingOutput()
        killed = False
        waits = 0

        def poll(self):
            return None if not self.killed else -9

        def kill(self):
            self.killed = True

        def wait(self, timeout):
            self.waits += 1
            return -9

    process = Process()
    with pytest.raises(ProgressProtocolError, match="timed out"):
        list(InstallerProcess(lambda *args, **kwargs: process, **timeouts).events())
    assert process.killed and process.waits >= 1


@pytest.mark.parametrize(
    ("quiet_seconds", "succeeds"),
    [
        (MAX_STAGE_TIMEOUT, True),
        (MAX_STAGE_TIMEOUT + INSTALL_IDLE_GRACE + 1, False),
    ],
)
def test_installer_watchdog_accepts_full_stage_budget_and_kills_after_deadline(
    quiet_seconds, succeeds
):
    class Clock:
        value = 0.0
        lock = threading.Lock()

        def __call__(self):
            with self.lock:
                return self.value

        def advance(self, seconds):
            with self.lock:
                self.value += seconds

    clock = Clock()

    class Output:
        calls = 0

        def readline(self, _limit):
            self.calls += 1
            if self.calls == 1:
                clock.advance(quiet_seconds)
                return (
                    json.dumps(
                        {"stage": "complete", "status": "done", "message": "Listo"}
                    ).encode()
                    + b"\n"
                )
            return b""

        def close(self):
            return None

    class Process:
        stdout = Output()
        killed = False
        waits = 0

        def poll(self):
            return None if not self.killed else -9

        def kill(self):
            self.killed = True

        def wait(self, timeout):
            self.waits += 1
            return -9 if self.killed else 0

    process = Process()
    installer = InstallerProcess(lambda *args, **kwargs: process, clock=clock)
    assert installer._overall_timeout == MAX_INSTALL_TOTAL_TIMEOUT
    assert installer._idle_timeout == MAX_STAGE_TIMEOUT + INSTALL_IDLE_GRACE
    if succeeds:
        assert list(installer.events())[-1].stage == "complete"
        assert process.killed is False
    else:
        with pytest.raises(ProgressProtocolError, match="timed out"):
            list(installer.events())
        assert process.killed is True and process.waits >= 1


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
        request_retry_decision=lambda _stage: RetryDecision.RETRY,
        defer=retries.append,
    )
    assert flow.start() is True
    assert calls == ["status", "register"]
    assert completed == [True]
    assert limited == []
    assert retries == []


def test_preinstalled_registration_declined_retry_enters_limited_and_completes_once():
    class Warp:
        def registration_status(self):
            return RegistrationStatus(False, "missing", 1, RegistrationState.UNREGISTERED)

        def register(self):
            return OperationResult(False, "failed", 7)

    class Tasks:
        def submit(self, worker, success, failure):
            success(worker())

    deferred = []
    limited = []
    completed = []
    flow = RegistrationCoordinator(
        warp=Warp(), tasks=Tasks(), request_terms=lambda: True,
        on_complete=lambda: completed.append(True),
        on_limited=lambda message: limited.append(message),
        request_retry_decision=lambda _stage: RetryDecision.LIMITED,
        defer=deferred.append,
    )
    flow.start()
    assert limited
    assert flow.limited_mode is True
    assert completed == [True]
    assert deferred == []
    assert flow.start() is False
    assert completed == [True]


def test_preinstalled_registration_retry_is_deferred_deduped_and_completes_once():
    calls = []

    class Warp:
        def registration_status(self):
            calls.append("status")
            return RegistrationStatus(False, "missing", 1, RegistrationState.UNREGISTERED)

        def register(self):
            calls.append("register")
            ok = calls.count("register") >= 2
            return OperationResult(ok, "", 0 if ok else 7)

    class Tasks:
        def submit(self, worker, success, failure):
            try:
                success(worker())
            except Exception as error:
                failure(error)

    deferred = []
    completed = []
    flow = RegistrationCoordinator(
        warp=Warp(), tasks=Tasks(), request_terms=lambda: True,
        on_complete=lambda: completed.append(True),
        on_limited=lambda _message: pytest.fail("unexpected limited mode"),
        request_retry_decision=lambda _stage: RetryDecision.RETRY,
        defer=deferred.append,
    )
    assert flow.start() is True
    assert flow.limited_mode is False
    assert completed == []
    assert len(deferred) == 1
    assert flow.start() is False
    assert len(deferred) == 1

    deferred.pop()()
    assert calls == ["status", "register", "register"]
    assert completed == [True]
    assert flow.start() is False
    assert completed == [True]


def test_preinstalled_status_exception_retries_status_stage_without_recursion():
    status_calls = []

    class Warp:
        def registration_status(self):
            status_calls.append(True)
            if len(status_calls) == 1:
                raise OSError("temporary")
            return RegistrationStatus(True, "", 0, RegistrationState.REGISTERED)

    class Tasks:
        def submit(self, worker, success, failure):
            try:
                success(worker())
            except Exception as error:
                failure(error)

    deferred, stages, completed = [], [], []
    flow = RegistrationCoordinator(
        warp=Warp(), tasks=Tasks(), request_terms=lambda: True,
        on_complete=lambda: completed.append(True),
        on_limited=lambda _message: pytest.fail("unexpected limited mode"),
        request_retry_decision=lambda stage: stages.append(stage) or RetryDecision.RETRY,
        defer=deferred.append,
    )
    flow.start()
    assert stages == [RetryStage.REGISTRATION_STATUS]
    assert len(deferred) == 1 and completed == []
    deferred.pop()()
    assert len(status_calls) == 2 and completed == [True]


def test_preinstalled_register_exception_retries_only_create_stage():
    register_calls = []

    class Warp:
        def registration_status(self):
            return RegistrationStatus(False, "missing", 1, RegistrationState.UNREGISTERED)

        def register(self):
            register_calls.append(True)
            if len(register_calls) == 1:
                raise OSError("temporary")
            return OperationResult(True, "", 0)

    class Tasks:
        def submit(self, worker, success, failure):
            try:
                success(worker())
            except Exception as error:
                failure(error)

    deferred, stages, completed = [], [], []
    flow = RegistrationCoordinator(
        warp=Warp(), tasks=Tasks(), request_terms=lambda: True,
        on_complete=lambda: completed.append(True),
        on_limited=lambda _message: pytest.fail("unexpected limited mode"),
        request_retry_decision=lambda stage: stages.append(stage) or RetryDecision.RETRY,
        defer=deferred.append,
    )
    flow.start()
    assert stages == [RetryStage.REGISTRATION_CREATE]
    deferred.pop()()
    assert len(register_calls) == 2 and completed == [True]
    assert flow.start() is False
    assert completed == [True]


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
