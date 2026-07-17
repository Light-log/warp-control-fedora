from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


class WarpState(str, Enum):
    CONNECTED = "connected"
    CONNECTING = "connecting"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    UNKNOWN = "unknown"


class RegistrationState(str, Enum):
    REGISTERED = "registered"
    UNREGISTERED = "unregistered"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class OperationResult:
    ok: bool
    output: str
    returncode: int


@dataclass(frozen=True)
class WarpStatus(OperationResult):
    state: WarpState


@dataclass(frozen=True)
class RegistrationStatus(OperationResult):
    state: RegistrationState


@dataclass(frozen=True)
class HostsResult(OperationResult):
    hosts: Tuple[str, ...]


@dataclass(frozen=True)
class ValueResult(OperationResult):
    value: Optional[str]


@dataclass(frozen=True)
class WarpCapabilities:
    ok: bool
    modes: Tuple[str, ...]
    protocols: Tuple[str, ...]
    host_remove_verb: str
    output: str
