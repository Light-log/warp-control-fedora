"""Purpose-only PolicyKit helpers for installing and restarting WARP."""

import io
import os
import select
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional, Sequence, TextIO

from warp_control.installers import installation_plan
from warp_control.installers.detector import SystemInfo, detect_system
from warp_control.installers.models import InstallAction
from warp_control.privileged.repositories import (
    APPROVED_APT_SOURCE_LINES,
    APT_PREFERENCES,
    APT_PREFERENCES_CONTENT,
    APT_KEY_URL,
    APT_KEYRING,
    APT_SOURCE,
    MAX_DOWNLOAD_BYTES,
    RPM_REPOSITORY,
    RPM_KEYRING,
    RPM_LOCAL_REPOSITORY_CONTENT,
    RPM_REPOSITORY_URL,
    RepositoryRejected,
    atomic_write,
    repository_config,
    validate_rpm_repository,
    validate_apt_candidate,
    validate_signing_key,
)
from warp_control.privileged.runner import JsonProgress, PrivilegedCommandRunner, exclusive_lock


DEFAULT_LOCK = Path("/run/lock/warp-control-privileged.lock")
# A package-manager stage may legitimately take fifteen minutes on a slow host.
MAX_STAGE_TIMEOUT = 900
# Four full stage budgets cover the roughly 3000-second worst-case supported
# plan (repository/key verification, metadata, packages and service) plus grace.
MAX_INSTALL_TOTAL_TIMEOUT = MAX_STAGE_TIMEOUT * 4
INSTALL_IDLE_GRACE = 60


class InvocationRejected(RuntimeError):
    pass


def _stdin_has_data(stream: TextIO) -> bool:
    if isinstance(stream, io.StringIO):
        return bool(stream.read(1))
    try:
        descriptor = stream.fileno()
    except (AttributeError, io.UnsupportedOperation):
        return bool(stream.read(1))
    try:
        if os.isatty(descriptor):
            readable, _, _ = select.select([descriptor], [], [], 0)
            return bool(readable and os.read(descriptor, 1))
        readable, _, _ = select.select([descriptor], [], [], 0)
        return bool(readable and os.read(descriptor, 1))
    except OSError as error:
        raise InvocationRejected("could not validate stdin") from error


def validate_invocation(argv: Sequence[str], stdin: TextIO, *, euid: Optional[int] = None) -> None:
    if len(argv) != 1:
        raise InvocationRejected("this helper accepts no arguments")
    if (os.geteuid() if euid is None else euid) != 0:
        raise InvocationRejected("the helper must run as root")
    if _stdin_has_data(stdin):
        raise InvocationRejected("stdin must be empty")


class InstallWarpHelper:
    def __init__(
        self,
        *,
        runner: Optional[PrivilegedCommandRunner] = None,
        detect: Callable[[], SystemInfo] = detect_system,
        progress: Optional[JsonProgress] = None,
        lock_path: Path = DEFAULT_LOCK,
        apt_keyring: Path = APT_KEYRING,
        apt_source: Path = APT_SOURCE,
        apt_preferences: Path = APT_PREFERENCES,
        rpm_repository: Path = RPM_REPOSITORY,
        rpm_keyring: Path = RPM_KEYRING,
    ) -> None:
        self.runner = runner or PrivilegedCommandRunner()
        self.detect = detect
        self.progress = progress or JsonProgress(sys.stdout)
        self.lock_path = Path(lock_path)
        self.apt_keyring = Path(apt_keyring)
        self.apt_source = Path(apt_source)
        self.apt_preferences = Path(apt_preferences)
        self.rpm_repository = Path(rpm_repository)
        self.rpm_keyring = Path(rpm_keyring)

    def _command(self, stage: str, message: str, argv: Sequence[str], timeout: int = 300):
        if not 0 < timeout <= MAX_STAGE_TIMEOUT:
            raise InvocationRejected("command timeout exceeds the approved stage budget")
        self.progress.emit(stage, "running", message)
        result = self.runner.run(argv, timeout=timeout)
        if not result.ok:
            raise InvocationRejected(f"{stage} failed with exit status {result.returncode}")
        self.progress.emit(stage, "done", message)
        return result

    def _download_verified_key(self, key_url: str) -> bytes:
        if key_url != APT_KEY_URL:
            raise RepositoryRejected("signing key URL is not approved")
        with tempfile.TemporaryDirectory(prefix="warp-control-key-", dir="/tmp") as directory:
            source = Path(directory) / "pubkey.gpg"
            dearmored = Path(directory) / "keyring.gpg"
            self._command(
                "repository",
                "Descargando la clave oficial de Cloudflare",
                (
                    "/usr/bin/curl", "--fail", "--silent", "--show-error", "--proto", "=https",
                    "--tlsv1.2", "--max-filesize", str(MAX_DOWNLOAD_BYTES), "--output", str(source), key_url,
                ),
            )
            if not source.is_file() or not 0 < source.stat().st_size <= MAX_DOWNLOAD_BYTES:
                raise RepositoryRejected("downloaded key has an invalid size")
            key_metadata = self._command(
                "repository", "Verificando la clave OpenPGP de Cloudflare",
                (
                    "/usr/bin/gpg", "--batch", "--no-options", "--homedir", directory,
                    "--no-auto-key-retrieve", "--with-colons", "--fingerprint",
                    "--show-keys", str(source),
                ),
            )
            validate_signing_key(key_metadata.stdout)
            self._command(
                "repository", "Creando el keyring firmado",
                (
                    "/usr/bin/gpg", "--batch", "--yes", "--no-options", "--homedir", directory,
                    "--no-auto-key-retrieve", "--dearmor", "--output", str(dearmored), str(source),
                ),
            )
            if not dearmored.is_file() or not 0 < dearmored.stat().st_size <= MAX_DOWNLOAD_BYTES:
                raise RepositoryRejected("generated keyring has an invalid size")
            return dearmored.read_bytes()

    def _install_rpm_repository(self, url: str, key_url: str) -> None:
        if url != RPM_REPOSITORY_URL or key_url != APT_KEY_URL:
            raise RepositoryRejected("RPM repository URL is not approved")
        self.rpm_repository.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=".cloudflare-warp.", dir=str(self.rpm_repository.parent))
        os.close(descriptor)
        temporary = Path(name)
        try:
            self._command(
                "repository",
                "Descargando el repositorio oficial de Cloudflare",
                (
                    "/usr/bin/curl", "--fail", "--silent", "--show-error", "--proto", "=https",
                    "--tlsv1.2", "--max-filesize", str(MAX_DOWNLOAD_BYTES), "--output", str(temporary), url,
                ),
            )
            contents = temporary.read_bytes()
            validate_rpm_repository(contents)
            keyring = self._download_verified_key(key_url)
            atomic_write(self.rpm_keyring, keyring)
            atomic_write(self.rpm_repository, RPM_LOCAL_REPOSITORY_CONTENT)
        finally:
            temporary.unlink(missing_ok=True)

    def _install_apt_repository(self, key_url: str, source_line: str) -> None:
        if key_url != APT_KEY_URL or source_line not in APPROVED_APT_SOURCE_LINES:
            raise RepositoryRejected("APT repository inputs are not approved")
        atomic_write(self.apt_keyring, self._download_verified_key(key_url))
        atomic_write(self.apt_source, source_line.encode("ascii"))
        atomic_write(self.apt_preferences, APT_PREFERENCES_CONTENT)

    def run(self) -> None:
        with exclusive_lock(self.lock_path):
            system = self.detect()
            plan = installation_plan(system)
            if not plan.supported:
                raise InvocationRejected("el sistema detectado no está soportado")
            config = repository_config(system)
            self.progress.emit("validation", "done", "Sistema compatible validado")
            if InstallAction.INSTALL_EPEL in plan.actions:
                self._command("epel", "Instalando EPEL confirmado por el usuario", ("/usr/bin/dnf", "-y", "install", "epel-release"))
            if config.family == "rpm" and config.repository_url and config.key_url:
                self._install_rpm_repository(config.repository_url, config.key_url)
                self._command("metadata", "Actualizando metadatos de Cloudflare", ("/usr/bin/dnf", "-q", "makecache", "--repo", "cloudflare-warp-stable"))
                self._command(
                    "packages", "Instalando Cloudflare WARP",
                    (
                        "/usr/bin/dnf", "-y", "repository-packages",
                        "cloudflare-warp-stable", "install", "cloudflare-warp",
                    ), 900,
                )
            elif config.family == "apt" and config.key_url and config.source_line:
                self._install_apt_repository(config.key_url, config.source_line)
                self._command("metadata", "Actualizando metadatos APT", ("/usr/bin/apt-get", "update"), 600)
                candidate = self._command(
                    "metadata", "Verificando el origen del paquete",
                    ("/usr/bin/apt-cache", "policy", "cloudflare-warp"),
                )
                validate_apt_candidate(candidate.stdout)
                self._command("packages", "Instalando Cloudflare WARP", ("/usr/bin/apt-get", "install", "-y", "cloudflare-warp"), 900)
            else:
                raise InvocationRejected("invalid repository configuration")
            self._command("service", "Activando warp-svc", ("/usr/bin/systemctl", "enable", "--now", "warp-svc.service"))
            self.progress.emit("complete", "done", "Cloudflare WARP quedó instalado")


class RestartWarpHelper:
    def __init__(
        self,
        *,
        runner=None,
        progress=None,
        lock_path: Path = DEFAULT_LOCK,
        detect: Callable[[], SystemInfo] = detect_system,
    ) -> None:
        self.runner = runner or PrivilegedCommandRunner()
        self.progress = progress or JsonProgress(sys.stdout)
        self.lock_path = Path(lock_path)
        self.detect = detect

    def run(self) -> None:
        with exclusive_lock(self.lock_path):
            if not installation_plan(self.detect()).supported:
                raise InvocationRejected("el sistema detectado no está soportado")
            self.progress.emit("service", "running", "Reiniciando warp-svc")
            result = self.runner.run(("/usr/bin/systemctl", "restart", "warp-svc.service"), timeout=90)
            if not result.ok:
                raise InvocationRejected(f"service failed with exit status {result.returncode}")
            self.progress.emit("service", "done", "warp-svc reiniciado")


def _main(helper, argv: Sequence[str], stdin: TextIO) -> int:
    try:
        validate_invocation(argv, stdin)
        helper.run()
        return 0
    except Exception as error:  # Boundary: never expose command output or traceback to the UI.
        try:
            helper.progress.emit("complete", "error", f"Operación rechazada: {type(error).__name__}")
        except Exception:
            pass
        return 1


def install_main() -> int:
    return _main(InstallWarpHelper(), sys.argv, sys.stdin)


def restart_main() -> int:
    return _main(RestartWarpHelper(), sys.argv, sys.stdin)
