from collections import deque

import pytest

from warp_control.commands import CommandResult
from warp_control.models import RegistrationState, WarpState
from warp_control.services.warp import WarpService


def result(ok=True, stdout="", stderr="", returncode=None):
    if returncode is None:
        returncode = 0 if ok else 1
    return CommandResult(ok, stdout, stderr, returncode)


class FakeRunner:
    def __init__(self, *results):
        self.results = deque(results)
        self.calls = []

    def run(self, argv, timeout=35):
        self.calls.append((list(argv), timeout))
        if not self.results:
            raise AssertionError(f"unexpected command: {argv}")
        return self.results.popleft()


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("Status update: Connected", WarpState.CONNECTED),
        ("Status update: Connecting", WarpState.CONNECTING),
        ("Status update: Reconnecting", WarpState.CONNECTING),
        ("Status update: Disconnected", WarpState.DISCONNECTED),
        ("Status update: Paused", WarpState.UNKNOWN),
    ],
)
def test_status_parses_cli_states_and_disconnected_precedes_connected(output, expected):
    runner = FakeRunner(result(stdout=output))

    status = WarpService(runner, "/opt/warp-cli").status()

    assert status.state is expected
    assert status.ok is True
    assert status.output == output
    assert runner.calls == [(["/opt/warp-cli", "--accept-tos", "status"], 35)]


def test_status_maps_command_failure_to_error_and_preserves_diagnostics():
    runner = FakeRunner(result(False, "partial", "daemon unavailable", 7))

    status = WarpService(runner, "warp-cli").status()

    assert status.state is WarpState.ERROR
    assert status.ok is False
    assert status.output == "partial\ndaemon unavailable"
    assert status.returncode == 7


def test_accept_tos_retries_without_flag_only_for_specific_option_error():
    runner = FakeRunner(
        result(False, stderr="error: unexpected argument '--accept-tos'", returncode=2),
        result(stdout="Connected"),
    )

    status = WarpService(runner, "warp-cli").status()

    assert status.state is WarpState.CONNECTED
    assert runner.calls == [
        (["warp-cli", "--accept-tos", "status"], 35),
        (["warp-cli", "status"], 35),
    ]


@pytest.mark.parametrize(
    "diagnostic",
    [
        "unknown mode supplied",
        "the daemon is unavailable",
        "accept-tos is required before proceeding",
        "accept-tos was accepted, but the requested mode is unknown",
    ],
)
def test_accept_tos_does_not_retry_arbitrary_failures(diagnostic):
    runner = FakeRunner(result(False, stderr=diagnostic))

    operation = WarpService(runner, "warp-cli").connect()

    assert operation.ok is False
    assert operation.output == diagnostic
    assert len(runner.calls) == 1


def test_connect_and_disconnect_return_typed_operation_results_with_exact_argv():
    runner = FakeRunner(result(stdout="connected"), result(False, stderr="busy", returncode=4))
    service = WarpService(runner, "warp-cli")

    connected = service.connect()
    disconnected = service.disconnect()

    assert connected.ok is True
    assert connected.output == "connected"
    assert disconnected.ok is False
    assert disconnected.returncode == 4
    assert runner.calls == [
        (["warp-cli", "--accept-tos", "connect"], 35),
        (["warp-cli", "--accept-tos", "disconnect"], 35),
    ]


def test_list_hosts_parses_and_preserves_wildcards():
    runner = FakeRunner(
        result(stdout="Excluded hosts:\nexample.com\n*.sub.example.com\nexample.com")
    )

    hosts = WarpService(runner, "warp-cli").list_hosts()

    assert hosts.ok is True
    assert hosts.hosts == ("*.sub.example.com", "example.com")
    assert runner.calls[0][0] == [
        "warp-cli",
        "--accept-tos",
        "tunnel",
        "host",
        "list",
    ]


def test_host_add_uses_current_add_verb():
    runner = FakeRunner(result())

    operation = WarpService(runner, "warp-cli").add_host("*.example.com")

    assert operation.ok is True
    assert runner.calls[0][0] == [
        "warp-cli",
        "--accept-tos",
        "tunnel",
        "host",
        "add",
        "*.example.com",
    ]


@pytest.mark.parametrize(("help_text", "verb"), [("add remove list", "remove"), ("add delete list", "delete")])
def test_host_remove_uses_verb_advertised_by_installed_help(help_text, verb):
    runner = FakeRunner(result(stdout=help_text), result())
    service = WarpService(runner, "warp-cli")

    operation = service.remove_host("example.com")

    assert operation.ok is True
    assert runner.calls == [
        (["warp-cli", "--accept-tos", "tunnel", "host", "--help"], 35),
        (["warp-cli", "--accept-tos", "tunnel", "host", verb, "example.com"], 35),
    ]


def test_registration_status_and_register_have_typed_results():
    runner = FakeRunner(
        result(stdout="Registration ID: abc"),
        result(False, stderr="No registration found", returncode=1),
        result(stdout="registered"),
    )
    service = WarpService(runner, "warp-cli")

    registered = service.registration_status()
    missing = service.registration_status()
    created = service.register()

    assert registered.state is RegistrationState.REGISTERED
    assert registered.ok is True
    assert missing.state is RegistrationState.UNREGISTERED
    assert missing.ok is False
    assert created.ok is True
    assert [call[0][-2:] for call in runner.calls] == [
        ["registration", "show"],
        ["registration", "show"],
        ["registration", "new"],
    ]


def test_registration_unrelated_failure_is_error():
    runner = FakeRunner(result(False, stderr="permission denied", returncode=13))

    registration = WarpService(runner, "warp-cli").registration_status()

    assert registration.state is RegistrationState.ERROR
    assert registration.output == "permission denied"


def test_capabilities_expose_only_known_values_from_installed_help():
    runner = FakeRunner(
        result(stdout="Modes: warp doh warp+doh dot warp+dot proxy tunnel_only future_mode"),
        result(stdout="Protocols: MASQUE WireGuard OtherProtocol"),
        result(stdout="Commands: add remove list"),
    )

    capabilities = WarpService(runner, "warp-cli").capabilities()

    assert capabilities.ok is True
    assert capabilities.modes == (
        "warp",
        "doh",
        "warp+doh",
        "dot",
        "warp+dot",
        "proxy",
        "tunnel_only",
    )
    assert capabilities.protocols == ("MASQUE", "WireGuard")
    assert capabilities.host_remove_verb == "remove"
    assert [call[0] for call in runner.calls] == [
        ["warp-cli", "--accept-tos", "mode", "--help"],
        ["warp-cli", "--accept-tos", "tunnel", "protocol", "--help"],
        ["warp-cli", "--accept-tos", "tunnel", "host", "--help"],
    ]


def test_capabilities_preserve_probe_failure_and_do_not_invent_values():
    runner = FakeRunner(
        result(False, stderr="mode help failed", returncode=8),
        result(stdout="Protocols: MASQUE"),
        result(False, stderr="host help failed", returncode=9),
    )

    capabilities = WarpService(runner, "warp-cli").capabilities()

    assert capabilities.ok is False
    assert capabilities.modes == ()
    assert capabilities.protocols == ("MASQUE",)
    assert capabilities.host_remove_verb == "remove"
    assert "mode help failed" in capabilities.output
    assert "host help failed" in capabilities.output


def test_get_mode_and_protocol_parse_only_supported_values():
    runner = FakeRunner(
        result(stdout="Mode: warp+doh"),
        result(stdout="Protocol: WireGuard"),
    )
    service = WarpService(runner, "warp-cli")

    mode = service.get_mode()
    protocol = service.get_protocol()

    assert mode.value == "warp+doh"
    assert protocol.value == "WireGuard"
    assert [call[0] for call in runner.calls] == [
        ["warp-cli", "--accept-tos", "mode"],
        ["warp-cli", "--accept-tos", "tunnel", "protocol", "get"],
    ]


def test_set_mode_rejects_unsupported_value_before_mutating_command():
    runner = FakeRunner(
        result(stdout="Modes: warp proxy"),
        result(stdout="Protocols: MASQUE"),
        result(stdout="Commands: remove"),
    )
    service = WarpService(runner, "warp-cli")

    operation = service.set_mode("doh")

    assert operation.ok is False
    assert "Unsupported mode" in operation.output
    assert len(runner.calls) == 3


def test_set_protocol_rejects_wrong_case_before_mutating_command():
    runner = FakeRunner(
        result(stdout="Modes: warp"),
        result(stdout="Protocols: MASQUE WireGuard"),
        result(stdout="Commands: remove"),
    )
    service = WarpService(runner, "warp-cli")

    operation = service.set_protocol("masque")

    assert operation.ok is False
    assert "Unsupported protocol" in operation.output
    assert len(runner.calls) == 3


def test_set_mode_and_protocol_expose_cli_success_and_nonzero_failure():
    runner = FakeRunner(
        result(stdout="Modes: warp proxy"),
        result(stdout="Protocols: MASQUE WireGuard"),
        result(stdout="Commands: remove"),
        result(stdout="mode changed"),
        result(False, stderr="protocol refused", returncode=6),
    )
    service = WarpService(runner, "warp-cli")

    mode = service.set_mode("proxy")
    protocol = service.set_protocol("MASQUE")

    assert mode.ok is True
    assert protocol.ok is False
    assert protocol.output == "protocol refused"
    assert protocol.returncode == 6
    assert runner.calls[-2][0] == ["warp-cli", "--accept-tos", "mode", "proxy"]
    assert runner.calls[-1][0] == [
        "warp-cli",
        "--accept-tos",
        "tunnel",
        "protocol",
        "set",
        "MASQUE",
    ]


def test_executable_resolver_is_supported_and_missing_path_is_typed_failure():
    runner = FakeRunner(result(stdout="Connected"))
    service = WarpService(runner, lambda: "/usr/local/bin/warp-cli")

    assert service.status().state is WarpState.CONNECTED
    assert runner.calls[0][0][0] == "/usr/local/bin/warp-cli"

    missing_runner = FakeRunner()
    missing = WarpService(missing_runner, lambda: None).connect()
    assert missing.ok is False
    assert missing.returncode == 127
    assert missing_runner.calls == []
