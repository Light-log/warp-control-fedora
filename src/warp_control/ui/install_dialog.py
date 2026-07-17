"""Headless-testable installation flow plus its optional GTK dialog."""

import json
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Iterator, Optional

from warp_control.installers.detector import Distribution, SystemInfo
from warp_control.installers.models import InstallAction, InstallPlan
from warp_control.models import OperationResult, RegistrationState, RegistrationStatus, WarpState
from warp_control.privileged.runner import PROGRESS_STAGES, PROGRESS_STATUSES


PKEXEC_ARGV = ("/usr/bin/pkexec", "/usr/libexec/warp-control/install-warp")
MAX_PROGRESS_LINE = 8192


class InstallDecision(str, Enum):
    INSTALL_NOW = "install_now"
    VIEW_INSTRUCTIONS = "view_instructions"
    NOT_NOW = "not_now"


class RetryDecision(str, Enum):
    RETRY = "retry"
    LIMITED = "limited"


class RetryStage(str, Enum):
    INSTALLATION = "installation"
    REGISTRATION_STATUS = "registration_status"
    REGISTRATION_CREATE = "registration_create"


class ProgressProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class InstallViewState:
    summary: str
    needs_confirmation: bool = False
    open_instructions: bool = False
    limited_mode: bool = False


@dataclass(frozen=True)
class ProgressEvent:
    stage: str
    status: str
    message: str


def build_pkexec_argv() -> tuple:
    return PKEXEC_ARGV


def parse_progress_line(line: str) -> ProgressEvent:
    if not isinstance(line, str) or not line or len(line.encode("utf-8")) > MAX_PROGRESS_LINE:
        raise ProgressProtocolError("invalid progress line size")
    try:
        payload = json.loads(line)
    except (TypeError, ValueError) as error:
        raise ProgressProtocolError("progress is not JSON") from error
    if not isinstance(payload, dict) or set(payload) != {"stage", "status", "message"}:
        raise ProgressProtocolError("progress has an invalid schema")
    stage, status, message = payload["stage"], payload["status"], payload["message"]
    if stage not in PROGRESS_STAGES or status not in PROGRESS_STATUSES:
        raise ProgressProtocolError("progress uses an unknown value")
    if not isinstance(message, str) or not message or len(message.encode("utf-8")) > 2048:
        raise ProgressProtocolError("progress has an invalid message")
    return ProgressEvent(stage, status, message)


class InstallPresenter:
    def __init__(self, system: SystemInfo, plan: InstallPlan) -> None:
        self.system = system
        self.plan = plan
        self.can_launch = False
        self.limited_mode = False
        self._awaiting_confirmation = False

    def _summary(self) -> str:
        changes = ["añadir el repositorio oficial", "instalar Cloudflare WARP", "activar warp-svc"]
        if InstallAction.INSTALL_EPEL in self.plan.actions:
            changes.insert(0, "instalar EPEL")
        return "Se autorizará: " + ", ".join(changes) + "."

    def choose(self, decision: InstallDecision) -> InstallViewState:
        self.can_launch = False
        self._awaiting_confirmation = False
        if decision is InstallDecision.NOT_NOW:
            self.limited_mode = True
            return InstallViewState("WARP Control continuará en modo limitado.", limited_mode=True)
        if decision is InstallDecision.VIEW_INSTRUCTIONS:
            if self.system.distribution in (
                Distribution.ARCH,
                Distribution.MANJARO,
                Distribution.ENDEAVOUROS,
            ):
                summary = (
                    "Cloudflare no publica un paquete oficial para Arch. "
                    "Consulta la sección experimental de la documentación de WARP Control; "
                    "ningún helper de AUR se ejecutará automáticamente."
                )
            else:
                summary = (
                    "Consulta las instrucciones oficiales en https://pkg.cloudflareclient.com/. "
                    "WARP Control no modificará el sistema mientras permanezcas en este flujo."
                )
            return InstallViewState(summary, open_instructions=True)
        if not self.plan.supported or self.system.distribution in (
            Distribution.ARCH,
            Distribution.MANJARO,
            Distribution.ENDEAVOUROS,
        ):
            return InstallViewState(
                self.plan.warning or "La instalación automática no está disponible.",
                open_instructions=True,
            )
        self._awaiting_confirmation = True
        return InstallViewState(self._summary(), needs_confirmation=True)

    def confirm_changes(self, accepted: bool) -> InstallViewState:
        self.can_launch = bool(
            accepted and self.plan.supported and self._awaiting_confirmation
        )
        self._awaiting_confirmation = False
        if not self.can_launch:
            self.limited_mode = True
            return InstallViewState("Instalación cancelada; se usará el modo limitado.", limited_mode=True)
        return InstallViewState("Autorización lista; PolicyKit solicitará autenticación.")

    def registration_argv(self, accepted_terms: bool) -> Optional[tuple]:
        if not accepted_terms:
            self.limited_mode = True
            return None
        return ("/usr/bin/warp-cli", "--accept-tos", "registration", "new")


class RegistrationCoordinator:
    """Check and create registration without depending on GTK."""

    def __init__(
        self,
        *,
        warp,
        tasks,
        request_terms: Callable[[], bool],
        on_complete: Callable[[], None],
        on_limited: Callable[[str], None],
        on_retry: Callable[[Callable[[], bool], str], None],
    ) -> None:
        self.warp = warp
        self.tasks = tasks
        self.request_terms = request_terms
        self.on_complete = on_complete
        self.on_limited = on_limited
        self.on_retry = on_retry
        self.limited_mode = False

    def start(self) -> bool:
        self.tasks.submit(
            self.warp.registration_status,
            self._status_complete,
            self._exception,
        )
        return True

    def _status_complete(self, status) -> None:
        if not isinstance(status, RegistrationStatus):
            self._fail("La respuesta del registro no es válida.")
            return
        if status.state is RegistrationState.REGISTERED:
            self.on_complete()
            return
        if status.state is not RegistrationState.UNREGISTERED:
            self._fail("No se pudo comprobar el registro de WARP.")
            return
        if not self.request_terms():
            self.limited_mode = True
            self.on_limited("No se aceptaron los términos; se continuará en modo limitado.")
            self.on_complete()
            return
        self.tasks.submit(self.warp.register, self._register_complete, self._exception)

    def _register_complete(self, result) -> None:
        if isinstance(result, OperationResult) and result.ok:
            self.on_complete()
            return
        self._fail("No se pudo crear el registro de WARP.")

    def _exception(self, _error: Exception) -> None:
        self._fail("La comprobación del registro terminó con un error.")

    def _fail(self, message: str) -> None:
        self.limited_mode = True
        self.on_limited(message)
        self.on_retry(self.start, message)


class RetryCoordinator:
    """Serialize user-directed retries and defer them to avoid recursive callbacks."""

    def __init__(
        self,
        *,
        request_decision: Callable[[RetryStage], RetryDecision],
        defer: Callable[[Callable[[], None]], None],
        on_limited: Callable[[], None],
    ) -> None:
        self.request_decision = request_decision
        self.defer = defer
        self.on_limited = on_limited
        self.retry_scheduled = False

    def recover(self, stage: RetryStage, retry: Callable[[], None]) -> bool:
        if self.retry_scheduled:
            return False
        if self.request_decision(stage) is not RetryDecision.RETRY:
            self.on_limited()
            return False
        self.retry_scheduled = True

        def run_once() -> None:
            self.retry_scheduled = False
            retry()

        self.defer(run_once)
        return True


class InstallerProcess:
    """Spawn only the fixed helper and validate every JSONL progress event."""

    def __init__(self, popen: Callable = subprocess.Popen) -> None:
        self._popen = popen

    def events(self) -> Iterator[ProgressEvent]:
        process = self._popen(
            list(build_pkexec_argv()),
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PATH": "/usr/bin:/bin"},
        )
        if process.stdout is None:
            raise ProgressProtocolError("helper progress pipe is unavailable")
        try:
            while True:
                line = process.stdout.readline(MAX_PROGRESS_LINE + 1)
                if not line:
                    break
                if len(line.encode("utf-8")) > MAX_PROGRESS_LINE or not line.endswith("\n"):
                    raise ProgressProtocolError("helper emitted an oversized progress line")
                yield parse_progress_line(line[:-1])
            returncode = process.wait(timeout=5)
            if returncode != 0:
                raise ProgressProtocolError(f"helper failed with exit status {returncode}")
        except BaseException:
            if process.poll() is None:
                process.kill()
            raise


# GTK is imported after all presenter contracts so headless tests stay independent.
try:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
except (ImportError, ValueError):  # pragma: no cover - distro packaging supplies GTK
    Gtk = None


if Gtk is not None:
    class InstallDialog(Gtk.Dialog):
        def __init__(self, parent, presenter: InstallPresenter) -> None:
            super().__init__(title="Instalar Cloudflare WARP", transient_for=parent, modal=True)
            self.presenter = presenter
            self.add_button("Ahora no", Gtk.ResponseType.CANCEL)
            self.add_button("Ver instrucciones", Gtk.ResponseType.HELP)
            self.add_button("Instalar ahora", Gtk.ResponseType.OK)
            content = self.get_content_area()
            content.set_border_width(18)
            title = Gtk.Label(label="Cloudflare WARP no está instalado")
            title.set_xalign(0)
            content.pack_start(title, False, False, 0)
            explanation = Gtk.Label(
                label=(presenter.plan.warning or "Puedes instalar el cliente oficial con autorización de administrador."),
                wrap=True,
            )
            explanation.set_xalign(0)
            content.pack_start(explanation, False, False, 10)
            self.show_all()

        def request_decision(self) -> InstallViewState:
            response = self.run()
            self.hide()
            mapping = {
                Gtk.ResponseType.OK: InstallDecision.INSTALL_NOW,
                Gtk.ResponseType.HELP: InstallDecision.VIEW_INSTRUCTIONS,
            }
            return self.presenter.choose(mapping.get(response, InstallDecision.NOT_NOW))

        def confirm_installation(self, summary: str) -> bool:
            dialog = Gtk.MessageDialog(
                transient_for=self.get_transient_for(),
                modal=True,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.NONE,
                text="Confirmar cambios del sistema",
            )
            dialog.format_secondary_text(summary)
            dialog.add_button("Cancelar", Gtk.ResponseType.CANCEL)
            dialog.add_button("Autorizar instalación", Gtk.ResponseType.OK)
            accepted = dialog.run() == Gtk.ResponseType.OK
            dialog.destroy()
            self.presenter.confirm_changes(accepted)
            return accepted


    class InstallProgressDialog(Gtk.Dialog):
        def __init__(self, parent) -> None:
            super().__init__(title="Instalando Cloudflare WARP", transient_for=parent, modal=True)
            self.set_deletable(False)
            self.label = Gtk.Label(label="Preparando autorización…", wrap=True)
            self.label.set_xalign(0)
            self.get_content_area().set_border_width(18)
            self.get_content_area().pack_start(self.label, False, False, 0)
            self.show_all()

        def apply_event(self, event: ProgressEvent) -> bool:
            self.label.set_text(event.message)
            return False


    def confirm_registration_terms(parent) -> bool:
        dialog = Gtk.MessageDialog(
            transient_for=parent,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text="Aceptar términos de Cloudflare",
        )
        dialog.format_secondary_text(
            "Para crear el registro de WARP debes aceptar expresamente los términos de Cloudflare."
        )
        dialog.add_button("Continuar en modo limitado", Gtk.ResponseType.CANCEL)
        dialog.add_button("Acepto y crear registro", Gtk.ResponseType.OK)
        accepted = dialog.run() == Gtk.ResponseType.OK
        dialog.destroy()
        return accepted


    class GtkInstallationFlow:
        """Drive installation off the GTK thread with injected task primitives."""

        def __init__(
            self,
            *,
            parent,
            presenter: InstallPresenter,
            tasks,
            idle_add,
            warp,
            on_complete: Callable[[], None],
            process: Optional[InstallerProcess] = None,
        ) -> None:
            self.parent = parent
            self.presenter = presenter
            self.tasks = tasks
            self.idle_add = idle_add
            self.warp = warp
            self.on_complete = on_complete
            self.process = process or InstallerProcess()
            self.progress = None
            self.recovery = RetryCoordinator(
                request_decision=self._request_retry_decision,
                defer=lambda callback: self.idle_add(callback),
                on_limited=self._continue_limited,
            )

        def _instructions(self, summary: str) -> None:
            dialog = Gtk.MessageDialog(
                transient_for=self.parent,
                modal=True,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.CLOSE,
                text="Instrucciones de instalación",
            )
            dialog.format_secondary_text(summary)
            dialog.run()
            dialog.destroy()

        def start(self) -> bool:
            dialog = InstallDialog(self.parent, self.presenter)
            state = dialog.request_decision()
            if state.open_instructions:
                dialog.destroy()
                self._instructions(state.summary)
                self.presenter.limited_mode = True
                return False
            if not state.needs_confirmation:
                dialog.destroy()
                return False
            accepted = dialog.confirm_installation(state.summary)
            dialog.destroy()
            if not accepted or not self.presenter.can_launch:
                return False
            self._submit_installation()
            return True

        def _submit_installation(self) -> None:
            if self.progress is None:
                self.progress = InstallProgressDialog(self.parent)
            self.tasks.submit(
                self._install,
                self._installation_complete,
                self._installation_failed,
            )

        def _install(self):
            for event in self.process.events():
                self.idle_add(self.progress.apply_event, event)
            return None

        def _installation_complete(self, _result) -> None:
            self._close_progress()
            self._submit_registration_status()

        def _submit_registration_status(self) -> None:
            self.tasks.submit(
                self.warp.registration_status,
                self._installed,
                self._registration_status_exception,
            )

        def _installed(self, registration) -> None:
            if not isinstance(registration, RegistrationStatus):
                self._registration_status_failed()
                return
            if registration.state is RegistrationState.UNREGISTERED:
                accepted = confirm_registration_terms(self.parent)
                if self.presenter.registration_argv(accepted) is None:
                    self.on_complete()
                    return
                self._submit_registration_create()
                return
            if registration.state is RegistrationState.REGISTERED:
                self.on_complete()
                return
            self._registration_status_failed()

        def _registration_status_failed(self) -> None:
            self.recovery.recover(
                RetryStage.REGISTRATION_STATUS,
                self._submit_registration_status,
            )

        def _submit_registration_create(self) -> None:
            self.tasks.submit(
                self.warp.register,
                self._registration_complete,
                self._registration_create_exception,
            )

        def _request_retry_decision(self, stage: RetryStage) -> RetryDecision:
            titles = {
                RetryStage.INSTALLATION: "La instalación no terminó",
                RetryStage.REGISTRATION_STATUS: "No se pudo comprobar el registro",
                RetryStage.REGISTRATION_CREATE: "No se pudo crear el registro",
            }
            dialog = Gtk.MessageDialog(
                transient_for=self.parent,
                modal=True,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.NONE,
                text=titles[stage],
            )
            dialog.format_secondary_text(
                "Puedes reintentar esta etapa o continuar en modo limitado."
            )
            dialog.add_button("Continuar en modo limitado", Gtk.ResponseType.CANCEL)
            dialog.add_button("Reintentar", Gtk.ResponseType.OK)
            decision = (
                RetryDecision.RETRY
                if dialog.run() == Gtk.ResponseType.OK
                else RetryDecision.LIMITED
            )
            dialog.destroy()
            return decision

        def _registration_complete(self, result) -> None:
            if isinstance(result, OperationResult) and result.ok:
                self.on_complete()
                return
            self.recovery.recover(
                RetryStage.REGISTRATION_CREATE,
                self._submit_registration_create,
            )

        def _installation_failed(self, _error: Exception) -> None:
            self._close_progress()
            self.recovery.recover(
                RetryStage.INSTALLATION,
                self._submit_installation,
            )

        def _registration_status_exception(self, _error: Exception) -> None:
            self.recovery.recover(
                RetryStage.REGISTRATION_STATUS,
                self._submit_registration_status,
            )

        def _registration_create_exception(self, _error: Exception) -> None:
            self.recovery.recover(
                RetryStage.REGISTRATION_CREATE,
                self._submit_registration_create,
            )

        def _close_progress(self) -> None:
            if self.progress is not None:
                self.progress.destroy()
                self.progress = None

        def _continue_limited(self) -> None:
            self._close_progress()
            self.presenter.limited_mode = True
            self.on_complete()


    class GtkRegistrationFlow:
        """GTK adapter around the headless registration coordinator."""

        def __init__(self, *, parent, warp, tasks, on_complete: Callable[[], None]) -> None:
            self.parent = parent
            self.coordinator = RegistrationCoordinator(
                warp=warp,
                tasks=tasks,
                request_terms=lambda: confirm_registration_terms(parent),
                on_complete=on_complete,
                on_limited=self._limited,
                on_retry=self._offer_retry,
            )

        def start(self) -> bool:
            return self.coordinator.start()

        def _limited(self, _message: str) -> None:
            self.parent.apply_state(WarpState.ERROR)

        def _offer_retry(self, retry: Callable[[], bool], message: str) -> None:
            dialog = Gtk.MessageDialog(
                transient_for=self.parent,
                modal=True,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.NONE,
                text="No se pudo completar el registro",
            )
            dialog.format_secondary_text(message)
            dialog.add_button("Continuar en modo limitado", Gtk.ResponseType.CANCEL)
            dialog.add_button("Reintentar", Gtk.ResponseType.OK)
            should_retry = dialog.run() == Gtk.ResponseType.OK
            dialog.destroy()
            if should_retry:
                retry()
