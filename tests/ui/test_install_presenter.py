import json

import pytest

from warp_control.installers import installation_plan
from warp_control.installers.detector import Architecture, Distribution, SystemInfo
from warp_control.ui.install_dialog import (
    InstallDecision,
    InstallerProcess,
    InstallPresenter,
    ProgressProtocolError,
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
