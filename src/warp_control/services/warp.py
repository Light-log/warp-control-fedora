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
_STATUS_LINE = re.compile(
    r"^\s*Status(?:\s+update)?\s*:\s*"
    r"(Connected|Connecting|Reconnecting|Disconnected)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


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
    option = r"['\"`]?--accept-tos['\"`]?"
    marker = r"(?:unknown|unexpected|unrecognized)"
    option_kind = r"(?:option|argument|flag)"
    before_option = rf"{marker}\s+{option_kind}\s*:?[ \t]*{option}"
    after_option = (
        rf"{option}\s+is\s+(?:an?\s+)?{marker}\s+{option_kind}"
    )
    return re.search(
        rf"(?:{before_option}|{after_option})", output, re.IGNORECASE
    ) is not None


def _probe_diagnostic(label: str, command: CommandResult) -> str:
    output = command.combined_output or "no diagnostic output"
    return f"{label} probe [returncode={command.returncode}]: {output}"


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
            matches = tuple(_STATUS_LINE.finditer(command.stdout))
            status_token = matches[-1].group(1).lower() if matches else ""
            states = {
                "connected": WarpState.CONNECTED,
                "connecting": WarpState.CONNECTING,
                "reconnecting": WarpState.CONNECTING,
                "disconnected": WarpState.DISCONNECTED,
            }
            state = states.get(status_token, WarpState.UNKNOWN)
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
        help_output = command.stdout if command.ok else ""
        advertised = set(
            re.findall(
                r"^\s*(remove|delete)\b",
                help_output,
                re.IGNORECASE | re.MULTILINE,
            )
        )
        advertised = {verb.lower() for verb in advertised}
        verb = "remove" if "remove" in advertised else (
            "delete" if "delete" in advertised else "remove"
        )
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
        if refresh:
            self._capabilities = None

        mode_help = self._run(["mode", "--help"])
        protocol_help = self._run(["tunnel", "protocol", "--help"])
        host_verb, host_help = self._probe_host_remove_verb()
        probes = (mode_help, protocol_help, host_help)
        diagnostics = tuple(
            _probe_diagnostic(label, probe)
            for label, probe in zip(
                ("mode", "protocol", "host"), probes
            )
        )
        capabilities = WarpCapabilities(
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
        if capabilities.ok:
            self._capabilities = capabilities
        return capabilities

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
        previous = self.get_mode()
        if not previous.ok or previous.value is None:
            return OperationResult(
                False, previous.output, previous.returncode
            )
        changed = self._run(["mode", mode])
        if changed.ok or previous.value == mode:
            return _operation(changed)
        rollback = self._run(["mode", previous.value])
        return self._failed_change_with_rollback(changed, rollback)

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
        previous = self.get_protocol()
        if not previous.ok or previous.value is None:
            return OperationResult(
                False, previous.output, previous.returncode
            )
        changed = self._run(["tunnel", "protocol", "set", protocol])
        if changed.ok or previous.value == protocol:
            return _operation(changed)
        rollback = self._run(
            ["tunnel", "protocol", "set", previous.value]
        )
        return self._failed_change_with_rollback(changed, rollback)

    @staticmethod
    def _failed_change_with_rollback(
        changed: CommandResult, rollback: CommandResult
    ) -> OperationResult:
        rollback_state = "succeeded" if rollback.ok else "failed"
        rollback_output = rollback.combined_output or "no diagnostic output"
        diagnostic = (
            f"{changed.combined_output}\n"
            f"Rollback {rollback_state}: {rollback_output}"
        )
        return OperationResult(False, diagnostic, changed.returncode)
