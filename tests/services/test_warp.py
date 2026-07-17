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


def test_status_uses_stdout_field_and_ignores_conflicting_stderr_diagnostic():
    runner = FakeRunner(
        result(
            stdout="Status: Connected\n",
            stderr="warning: previously disconnected\n",
        )
    )

    status = WarpService(runner, "warp-cli").status()

    assert status.state is WarpState.CONNECTED
    assert "previously disconnected" in status.output


@pytest.mark.parametrize(
    "stdout",
    [
        "Connected to daemon, but no status field",
        "Last Status: Connected",
        "Status: Connected with MASQUE",
        "No status available",
    ],
)
def test_status_does_not_infer_state_from_noisy_stdout(stdout):
    runner = FakeRunner(result(stdout=stdout))

    status = WarpService(runner, "warp-cli").status()

    assert status.state is WarpState.UNKNOWN


@pytest.mark.parametrize(
    "diagnostic",
    [
        "unknown option --accept-tos",
        "unrecognized argument '--accept-tos'",
        "unexpected flag: --accept-tos",
        "--accept-tos is an unknown option",
        "--accept-tos is an unrecognized argument",
    ],
)
def test_accept_tos_retries_without_flag_only_for_specific_option_error(
    diagnostic,
):
    runner = FakeRunner(
        result(False, stderr=diagnostic, returncode=2),
        result(stdout="Status: Connected"),
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
        "accept-tos: unknown mode",
        "accept-tos was accepted, but the requested mode is unknown",
        "--accept-tos unexpected daemon failure",
        "--accept-tos unknown mode",
        "unexpected daemon failure near --accept-tos",
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


@pytest.mark.parametrize(
    ("help_text", "verb"),
    [
        ("  add HOST\n  remove HOST  Remove an excluded host\n  list", "remove"),
        ("delete  Remove an excluded host", "delete"),
        (
            "delete  Legacy removal command\nremove  Remove an excluded host",
            "remove",
        ),
        ("Use delete to remove an excluded host", "remove"),
    ],
)
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
    assert "mode probe [returncode=8]" in capabilities.output
    assert "protocol probe [returncode=0]" in capabilities.output
    assert "host probe [returncode=9]" in capabilities.output


def test_transient_capability_failure_is_not_cached_and_next_probe_recovers():
    runner = FakeRunner(
        result(False, stderr="temporary mode failure", returncode=8),
        result(stdout="Protocols: MASQUE"),
        result(stdout="delete  Remove an excluded host"),
        result(stdout="Modes: warp proxy"),
        result(stdout="Protocols: MASQUE WireGuard"),
        result(stdout="remove  Remove an excluded host"),
    )
    service = WarpService(runner, "warp-cli")

    failed = service.capabilities()
    recovered = service.capabilities()
    cached = service.capabilities()

    assert failed.ok is False
    assert failed.modes == ()
    assert failed.host_remove_verb == "delete"
    assert recovered.ok is True
    assert recovered.modes == ("warp", "proxy")
    assert recovered.protocols == ("MASQUE", "WireGuard")
    assert recovered.host_remove_verb == "remove"
    assert cached is recovered
    assert len(runner.calls) == 6
    assert [call[0][-2:] for call in runner.calls] == [
        ["mode", "--help"],
        ["protocol", "--help"],
        ["host", "--help"],
        ["mode", "--help"],
        ["protocol", "--help"],
        ["host", "--help"],
    ]


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


@pytest.mark.parametrize(
    ("setter", "value", "current_output", "query_argv", "mutation_argv"),
    [
        (
            "set_mode",
            "proxy",
            "Mode: warp",
            ["warp-cli", "--accept-tos", "mode"],
            ["warp-cli", "--accept-tos", "mode", "proxy"],
        ),
        (
            "set_protocol",
            "MASQUE",
            "Protocol: WireGuard",
            ["warp-cli", "--accept-tos", "tunnel", "protocol", "get"],
            [
                "warp-cli",
                "--accept-tos",
                "tunnel",
                "protocol",
                "set",
                "MASQUE",
            ],
        ),
    ],
)
def test_setter_captures_current_value_then_exposes_success(
    setter, value, current_output, query_argv, mutation_argv
):
    runner = FakeRunner(
        result(stdout="Modes: warp proxy"),
        result(stdout="Protocols: MASQUE WireGuard"),
        result(stdout="Commands: remove"),
        result(stdout=current_output),
        result(stdout="changed"),
    )
    service = WarpService(runner, "warp-cli")

    operation = getattr(service, setter)(value)

    assert operation.ok is True
    assert operation.output == "changed"
    assert [call[0] for call in runner.calls[-2:]] == [query_argv, mutation_argv]


@pytest.mark.parametrize(
    ("setter", "value", "current_output", "mutation_argv", "rollback_argv"),
    [
        (
            "set_mode",
            "proxy",
            "Mode: warp",
            ["warp-cli", "--accept-tos", "mode", "proxy"],
            ["warp-cli", "--accept-tos", "mode", "warp"],
        ),
        (
            "set_protocol",
            "MASQUE",
            "Protocol: WireGuard",
            [
                "warp-cli",
                "--accept-tos",
                "tunnel",
                "protocol",
                "set",
                "MASQUE",
            ],
            [
                "warp-cli",
                "--accept-tos",
                "tunnel",
                "protocol",
                "set",
                "WireGuard",
            ],
        ),
    ],
)
def test_failed_setter_rolls_back_known_different_value_and_keeps_original_failure(
    setter, value, current_output, mutation_argv, rollback_argv
):
    runner = FakeRunner(
        result(stdout="Modes: warp proxy"),
        result(stdout="Protocols: MASQUE WireGuard"),
        result(stdout="Commands: remove"),
        result(stdout=current_output),
        result(False, stderr="change refused", returncode=6),
        result(stdout="restored"),
    )
    service = WarpService(runner, "warp-cli")

    operation = getattr(service, setter)(value)

    assert operation.ok is False
    assert operation.returncode == 6
    assert "change refused" in operation.output
    assert "restored" in operation.output
    assert [call[0] for call in runner.calls[-2:]] == [
        mutation_argv,
        rollback_argv,
    ]


@pytest.mark.parametrize(
    ("setter", "value", "query_argv", "mutation_argv"),
    [
        (
            "set_mode",
            "proxy",
            ["warp-cli", "--accept-tos", "mode"],
            ["warp-cli", "--accept-tos", "mode", "proxy"],
        ),
        (
            "set_protocol",
            "MASQUE",
            ["warp-cli", "--accept-tos", "tunnel", "protocol", "get"],
            [
                "warp-cli",
                "--accept-tos",
                "tunnel",
                "protocol",
                "set",
                "MASQUE",
            ],
        ),
    ],
)
def test_failed_prior_query_stops_before_mutation(
    setter, value, query_argv, mutation_argv
):
    runner = FakeRunner(
        result(stdout="Modes: warp proxy"),
        result(stdout="Protocols: MASQUE WireGuard"),
        result(stdout="Commands: remove"),
        result(False, stderr="query failed", returncode=5),
    )
    service = WarpService(runner, "warp-cli")

    operation = getattr(service, setter)(value)

    assert operation.ok is False
    assert operation.returncode == 5
    assert operation.output == "query failed"
    assert runner.calls[-1][0] == query_argv
    assert mutation_argv not in [call[0] for call in runner.calls]


def test_executable_resolver_is_supported_and_missing_path_is_typed_failure():
    runner = FakeRunner(result(stdout="Status: Connected"))
    service = WarpService(runner, lambda: "/usr/local/bin/warp-cli")

    assert service.status().state is WarpState.CONNECTED
    assert runner.calls[0][0][0] == "/usr/local/bin/warp-cli"

    missing_runner = FakeRunner()
    missing = WarpService(missing_runner, lambda: None).connect()
    assert missing.ok is False
    assert missing.returncode == 127
    assert missing_runner.calls == []
