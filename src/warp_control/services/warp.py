import re
from typing import Callable, Optional, Sequence, Tuple, Union

from warp_control.commands import CommandResult, CommandRunner
from warp_control.domains import parse_hosts
from warp_control.models import (
    HostsResult,
    OperationResult,
    RegistrationState,
    RegistrationStatus,
    ValueResult,
    WarpCapabilities,
    WarpState,
    WarpStatus,
)


_KNOWN_MODES = (
    "warp",
    "doh",
    "warp+doh",
    "dot",
    "warp+dot",
    "proxy",
    "tunnel_only",
)
_KNOWN_PROTOCOLS = ("MASQUE", "WireGuard")
_Executable = Union[str, Callable[[], Optional[str]]]


def _operation(command: CommandResult) -> OperationResult:
    return OperationResult(
        command.ok, command.combined_output, command.returncode
    )


def _advertised(output: str, known: Tuple[str, ...]) -> Tuple[str, ...]:
    values = []
    for value in known:
        pattern = rf"(?<![\w+]){re.escape(value)}(?![\w+])"
        if re.search(pattern, output):
            values.append(value)
    return tuple(values)


def _accept_tos_is_unsupported(output: str) -> bool:
    option = r"(?:--)?accept-tos"
    marker = r"(?:unknown|unexpected|unrecognized)"
    before_option = rf"{marker}(?:\s+\w+){{0,3}}\s+['\"`]*{option}"
    after_option = rf"{option}['\"`:]*\s+(?:is\s+)?{marker}"
    return re.search(
        rf"(?:{before_option}|{after_option})", output, re.IGNORECASE
    ) is not None


class WarpService:
    def __init__(
        self,
        runner: CommandRunner,
        executable: _Executable = "warp-cli",
        resolver: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        self._runner = runner
        self._executable = executable
        self._resolver = resolver
        self._capabilities: Optional[WarpCapabilities] = None

    def _resolve_executable(self) -> Optional[str]:
        try:
            if self._resolver is not None:
                if not isinstance(self._executable, str):
                    return None
                return self._resolver(self._executable)
            if callable(self._executable):
                return self._executable()
            return self._executable
        except OSError:
            return None

    def _run(self, arguments: Sequence[str], timeout: int = 35) -> CommandResult:
        executable = self._resolve_executable()
        if not executable:
            return CommandResult(
                False, "", "warp-cli executable was not found", 127
            )

        with_acceptance = [executable, "--accept-tos", *arguments]
        command = self._runner.run(with_acceptance, timeout=timeout)
        unsupported_acceptance = _accept_tos_is_unsupported(
            command.combined_output
        )
        if command.ok or not unsupported_acceptance:
            return command
        return self._runner.run([executable, *arguments], timeout=timeout)

    def status(self) -> WarpStatus:
        command = self._run(["status"])
        output = command.combined_output
        if not command.ok:
            state = WarpState.ERROR
        else:
            lowered = output.lower()
            if "disconnected" in lowered:
                state = WarpState.DISCONNECTED
            elif "reconnecting" in lowered or "connecting" in lowered:
                state = WarpState.CONNECTING
            elif "connected" in lowered:
                state = WarpState.CONNECTED
            else:
                state = WarpState.UNKNOWN
        return WarpStatus(command.ok, output, command.returncode, state)

    def connect(self) -> OperationResult:
        return _operation(self._run(["connect"]))

    def disconnect(self) -> OperationResult:
        return _operation(self._run(["disconnect"]))

    def list_hosts(self) -> HostsResult:
        command = self._run(["tunnel", "host", "list"])
        hosts = parse_hosts(command.stdout) if command.ok else ()
        return HostsResult(
            command.ok,
            command.combined_output,
            command.returncode,
            hosts,
        )

    def add_host(self, rule: str) -> OperationResult:
        return _operation(self._run(["tunnel", "host", "add", rule]))

    def _probe_host_remove_verb(self) -> Tuple[str, CommandResult]:
        command = self._run(["tunnel", "host", "--help"])
        advertised = set(re.findall(r"[A-Za-z_]+", command.combined_output.lower()))
        verb = "delete" if "delete" in advertised and "remove" not in advertised else "remove"
        return verb, command

    def remove_host(self, rule: str) -> OperationResult:
        if self._capabilities is None:
            verb, _ = self._probe_host_remove_verb()
        else:
            verb = self._capabilities.host_remove_verb
        return _operation(self._run(["tunnel", "host", verb, rule]))

    def registration_status(self) -> RegistrationStatus:
        command = self._run(["registration", "show"])
        output = command.combined_output
        if command.ok:
            state = RegistrationState.REGISTERED
        else:
            lowered = output.lower()
            missing = (
                "no registration" in lowered
                or "not registered" in lowered
                or "unregistered" in lowered
                or "registration not found" in lowered
            )
            state = (
                RegistrationState.UNREGISTERED
                if missing
                else RegistrationState.ERROR
            )
        return RegistrationStatus(command.ok, output, command.returncode, state)

    def register(self) -> OperationResult:
        return _operation(self._run(["registration", "new"]))

    def capabilities(self, refresh: bool = False) -> WarpCapabilities:
        if self._capabilities is not None and not refresh:
            return self._capabilities

        mode_help = self._run(["mode", "--help"])
        protocol_help = self._run(["tunnel", "protocol", "--help"])
        host_verb, host_help = self._probe_host_remove_verb()
        probes = (mode_help, protocol_help, host_help)
        diagnostics = tuple(
            probe.combined_output for probe in probes if probe.combined_output
        )
        self._capabilities = WarpCapabilities(
            ok=all(probe.ok for probe in probes),
            modes=_advertised(mode_help.combined_output, _KNOWN_MODES)
            if mode_help.ok
            else (),
            protocols=_advertised(
                protocol_help.combined_output, _KNOWN_PROTOCOLS
            )
            if protocol_help.ok
            else (),
            host_remove_verb=host_verb,
            output="\n".join(diagnostics),
        )
        return self._capabilities

    def get_mode(self) -> ValueResult:
        command = self._run(["mode"])
        values = _advertised(command.combined_output, _KNOWN_MODES)
        value = values[0] if command.ok and len(values) == 1 else None
        return ValueResult(
            command.ok and value is not None,
            command.combined_output,
            command.returncode,
            value,
        )

    def set_mode(self, mode: str) -> OperationResult:
        capabilities = self.capabilities()
        if mode not in capabilities.modes:
            return OperationResult(False, f"Unsupported mode: {mode}", 2)
        return _operation(self._run(["mode", mode]))

    def get_protocol(self) -> ValueResult:
        command = self._run(["tunnel", "protocol", "get"])
        values = _advertised(command.combined_output, _KNOWN_PROTOCOLS)
        value = values[0] if command.ok and len(values) == 1 else None
        return ValueResult(
            command.ok and value is not None,
            command.combined_output,
            command.returncode,
            value,
        )

    def set_protocol(self, protocol: str) -> OperationResult:
        capabilities = self.capabilities()
        if protocol not in capabilities.protocols:
            return OperationResult(
                False, f"Unsupported protocol: {protocol}", 2
            )
        return _operation(
            self._run(["tunnel", "protocol", "set", protocol])
        )
