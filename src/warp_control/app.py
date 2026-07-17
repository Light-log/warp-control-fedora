"""Application controller and GTK bootstrap for WARP Control."""

import argparse
import logging
import os
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, Tuple

from warp_control.config import Config
from warp_control.domains import expand_host_rule
from warp_control.models import (
    HostsResult,
    OperationResult,
    WarpCapabilities,
    WarpState,
    WarpStatus,
)
from warp_control.ui.presenters import UIActions


@dataclass(frozen=True)
class RefreshSnapshot:
    status: WarpStatus
    hosts: HostsResult
    capabilities: WarpCapabilities
    mode: Optional[str]
    protocol: Optional[str]


class ApplicationController:
    """Coordinate injected services without performing blocking work in GTK."""

    def __init__(
        self,
        *,
        config: Config,
        warp: Any,
        icons: Any,
        autostart: Any,
        diagnostics: Any,
        tasks: Any,
        scheduler: Any,
        window: Any,
        tray: Any,
        logger: Optional[logging.Logger] = None,
        quit_mainloop: Callable[[], None] = lambda: None,
    ) -> None:
        self.config = config
        self.warp = warp
        self.icons = icons
        self.autostart = autostart
        self.diagnostics = diagnostics
        self.tasks = tasks
        self.scheduler = scheduler
        self.window = window
        self.tray = tray
        self.logger = logger or logging.getLogger("warp_control")
        self._quit_mainloop = quit_mainloop
        self.refreshing = False
        self._shutdown = False
        self._state = WarpState.UNKNOWN
        self._mode: Optional[str] = None
        self._protocol: Optional[str] = None

    def ui_actions(self) -> UIActions:
        return UIActions(
            on_toggle_connection=self.toggle_connection,
            on_add_host=self.add_host,
            on_remove_host=self.remove_host,
            on_theme_changed=self.set_theme,
            on_color_changed=self.set_state_color,
            on_accent_changed=self.set_accent,
            on_reset_appearance=self.reset_appearance,
            on_autostart_changed=self.set_autostart,
            on_auto_update_changed=self.set_auto_update,
            on_interval_changed=self.set_update_interval,
            on_mode_changed=self.set_mode,
            on_protocol_changed=self.set_protocol,
            on_restart_service=self.restart_service,
            on_test_connection=self.check_connectivity,
            on_open_log=self.open_log,
        )

    def start(self, *, background: bool = False) -> None:
        self.window.apply_config(self.config)
        initial_icon = self._render_icon(WarpState.UNKNOWN)
        if initial_icon is not None:
            self.window.apply_state(WarpState.UNKNOWN, initial_icon)
            self.tray.start(initial_icon)
        else:
            self.window.apply_state(WarpState.UNKNOWN)
        self._reschedule()
        self.refresh()
        if not background:
            self.show_panel()

    def refresh(self) -> bool:
        if self._shutdown or self.refreshing:
            return False
        self.refreshing = True

        def collect() -> RefreshSnapshot:
            status = self.warp.status()
            hosts = self.warp.list_hosts()
            capabilities = self.warp.capabilities()
            mode_result = self.warp.get_mode()
            protocol_result = self.warp.get_protocol()
            return RefreshSnapshot(
                status,
                hosts,
                capabilities,
                mode_result.value if mode_result.ok else None,
                protocol_result.value if protocol_result.ok else None,
            )

        self.tasks.submit(collect, self._refresh_complete, self._refresh_failed)
        return True

    def _refresh_complete(self, snapshot: RefreshSnapshot) -> None:
        self.refreshing = False
        if not self._shutdown:
            self._apply_snapshot(snapshot)

    def _refresh_failed(self, error: Exception) -> None:
        self.refreshing = False
        self.logger.error("refresh failed: %s", error)
        if not self._shutdown:
            self._state = WarpState.ERROR
            icon = self._render_icon(WarpState.ERROR)
            self.window.apply_state(WarpState.ERROR, icon)
            if icon is not None:
                self.tray.update_icon(icon)

    def _apply_snapshot(self, snapshot: RefreshSnapshot) -> None:
        self._state = snapshot.status.state
        if snapshot.mode is not None:
            self._mode = snapshot.mode
        if snapshot.protocol is not None:
            self._protocol = snapshot.protocol
        icon = self._render_icon(self._state)
        self.window.apply_state(self._state, icon)
        if snapshot.hosts.ok:
            self.window.set_hosts(snapshot.hosts.hosts)
        self.window.set_capabilities(
            snapshot.capabilities, self._mode, self._protocol
        )
        self.window.apply_connection_settings(self._mode, self._protocol)
        if icon is not None:
            self.tray.update_icon(icon)
        self.logger.info(
            "refresh state=%s status_rc=%s hosts_rc=%s capabilities_ok=%s",
            self._state.value,
            snapshot.status.returncode,
            snapshot.hosts.returncode,
            snapshot.capabilities.ok,
        )

    def toggle_connection(self) -> None:
        disconnect = self._state is WarpState.CONNECTED
        self._state = WarpState.CONNECTING
        self.window.apply_state(WarpState.CONNECTING)
        operation = self.warp.disconnect if disconnect else self.warp.connect
        self._submit_operation(operation, refresh=True)

    def add_host(self, value: str, include_subdomains: bool) -> None:
        try:
            rules = expand_host_rule(value, include_subdomains)
        except ValueError as error:
            self.logger.warning("invalid host rule: %s", error)
            return

        def worker() -> OperationResult:
            last = OperationResult(True, "", 0)
            for rule in rules:
                last = self.warp.add_host(rule)
                if not last.ok:
                    return last
            return last

        self._submit_operation(worker, refresh=True)

    def remove_host(self, host: str) -> None:
        self._submit_operation(lambda: self.warp.remove_host(host), refresh=True)

    def set_mode(self, mode: str) -> None:
        previous = {"mode": self._mode, "protocol": self._protocol}

        def worker() -> Tuple[OperationResult, Optional[str], Optional[str]]:
            previous_mode = previous["mode"]
            previous_protocol = previous["protocol"]
            if previous_mode is None:
                current = self.warp.get_mode()
                previous_mode = current.value if current.ok else None
                previous["mode"] = previous_mode
            if previous_protocol is None:
                current = self.warp.get_protocol()
                previous_protocol = current.value if current.ok else None
                previous["protocol"] = previous_protocol
            return self.warp.set_mode(mode), previous_mode, previous_protocol

        def complete(
            change: Tuple[OperationResult, Optional[str], Optional[str]]
        ) -> None:
            result, previous_mode, previous_protocol = change
            self._log_result("set mode", result)
            if not result.ok:
                self.window.apply_connection_settings(
                    previous_mode, previous_protocol
                )
            self.refresh()

        def failed(error: Exception) -> None:
            self.window.apply_connection_settings(
                previous["mode"], previous["protocol"]
            )
            self._operation_failed(error)

        self.tasks.submit(worker, complete, failed)

    def set_protocol(self, protocol: str) -> None:
        previous = {"mode": self._mode, "protocol": self._protocol}

        def worker() -> Tuple[OperationResult, Optional[str], Optional[str]]:
            previous_mode = previous["mode"]
            previous_protocol = previous["protocol"]
            if previous_mode is None:
                current = self.warp.get_mode()
                previous_mode = current.value if current.ok else None
                previous["mode"] = previous_mode
            if previous_protocol is None:
                current = self.warp.get_protocol()
                previous_protocol = current.value if current.ok else None
                previous["protocol"] = previous_protocol
            return (
                self.warp.set_protocol(protocol),
                previous_mode,
                previous_protocol,
            )

        def complete(
            change: Tuple[OperationResult, Optional[str], Optional[str]]
        ) -> None:
            result, previous_mode, previous_protocol = change
            self._log_result("set protocol", result)
            if not result.ok:
                self.window.apply_connection_settings(
                    previous_mode, previous_protocol
                )
            self.refresh()

        def failed(error: Exception) -> None:
            self.window.apply_connection_settings(
                previous["mode"], previous["protocol"]
            )
            self._operation_failed(error)

        self.tasks.submit(worker, complete, failed)

    def restart_service(self) -> None:
        self._submit_operation(self.diagnostics.restart_service, refresh=True)

    def check_connectivity(self) -> None:
        self._submit_operation(self.diagnostics.check_connectivity)

    def open_log(self) -> None:
        self._submit_operation(self.diagnostics.open_log)

    def _submit_operation(
        self, worker: Callable[[], OperationResult], *, refresh: bool = False
    ) -> None:
        def complete(result: OperationResult) -> None:
            self._log_result("operation", result)
            if refresh:
                self.refresh()

        self.tasks.submit(worker, complete, self._operation_failed)

    def _operation_failed(self, error: Exception) -> None:
        self.logger.error("background operation failed: %s", error)
        self.refresh()

    def _log_result(self, action: str, result: OperationResult) -> None:
        method = self.logger.info if result.ok else self.logger.error
        method("%s ok=%s returncode=%s output=%s", action, result.ok,
               result.returncode, result.output)

    def set_theme(self, theme: str) -> None:
        if theme not in {"light", "dark"}:
            return
        self.config.theme = theme
        self._save_and_apply(render_icons=False)

    def set_accent(self, accent: str) -> None:
        self.config.accent = accent
        self._save_and_apply(render_icons=False)

    def set_state_color(self, state: str, role: str, color: str) -> None:
        if state not in self.config.colors or role not in {"primary", "secondary"}:
            return
        self.config.colors[state][role] = color
        self._save_and_apply(render_icons=True)

    def reset_appearance(self) -> None:
        autostart = self.config.autostart_enabled
        auto_update = self.config.auto_update_enabled
        interval = self.config.update_interval_seconds
        defaults = Config(path=self.config.path)
        self.config.theme = defaults.theme
        self.config.accent = defaults.accent
        self.config.colors = deepcopy(defaults.colors)
        self.config.autostart_enabled = autostart
        self.config.auto_update_enabled = auto_update
        self.config.update_interval_seconds = interval
        self._save_and_apply(render_icons=True)

    def set_autostart(self, enabled: bool) -> None:
        try:
            self.autostart.enable() if enabled else self.autostart.disable()
        except (OSError, ValueError) as error:
            self.logger.error("autostart change failed: %s", error)
            self.window.apply_config(self.config)
            return
        self.config.autostart_enabled = bool(enabled)
        self._save_and_apply(render_icons=False)

    def set_auto_update(self, enabled: bool) -> None:
        self.config.auto_update_enabled = bool(enabled)
        self._save_and_apply(render_icons=False)
        self._reschedule()

    def set_update_interval(self, interval: int) -> None:
        if isinstance(interval, bool) or interval <= 0:
            return
        self.config.update_interval_seconds = interval
        self._save_and_apply(render_icons=False)
        self._reschedule()

    def _save_and_apply(self, *, render_icons: bool) -> None:
        self.config.save()
        self.window.apply_config(self.config)
        if render_icons:
            icon = self._render_icon(self._state)
            if icon is not None:
                self.window.apply_state(self._state, icon)
                self.tray.update_icon(icon)

    def _render_icon(self, state: WarpState) -> Optional[Path]:
        try:
            return Path(self.icons.render(state, self.config))
        except (OSError, ValueError) as error:
            self.logger.error("icon render failed: %s", error)
            return None

    def _reschedule(self) -> None:
        self.scheduler.stop()
        if self.config.auto_update_enabled and not self._shutdown:
            self.scheduler.start(
                self.refresh, self.config.update_interval_seconds
            )

    def show_panel(self) -> None:
        self.window.show_compact()
        self.window.show_all()
        self.window.present()

    def toggle_panel(self) -> None:
        if self.window.get_visible():
            self.window.hide()
        else:
            self.show_panel()

    def quit(self) -> None:
        self.shutdown()
        self._quit_mainloop()

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        self.scheduler.stop()
        self.tray.close()


def _cache_dir() -> Path:
    configured = os.environ.get("XDG_CACHE_HOME")
    base = Path(configured) if configured and Path(configured).is_absolute() else None
    return (base or Path.home() / ".cache") / "warp-control" / "icons"


def _build_runtime(config: Config):
    """Import GTK only for the executable path, keeping controller tests headless."""
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk

    init_result = Gtk.init_check()
    initialized = init_result[0] if isinstance(init_result, tuple) else init_result
    if not initialized:
        raise RuntimeError("no hay una sesión gráfica GTK disponible")

    from warp_control.commands import CommandRunner
    from warp_control.services.autostart import AutostartService
    from warp_control.services.diagnostics import (
        DiagnosticsService,
        configure_logging,
    )
    from warp_control.services.icons import IconRenderer
    from warp_control.services.tasks import BackgroundTasks, PeriodicScheduler
    from warp_control.services.warp import WarpService
    from warp_control.tray import TrayActions, TrayManager
    from warp_control.ui.assets import runtime_asset_path
    from warp_control.ui.main_window import MainWindow

    runner = CommandRunner()
    logger = configure_logging()
    holder = {}
    # The controller does not yet exist, so callbacks deliberately resolve it
    # at invocation time.
    proxy = _action_proxy(holder)
    window = MainWindow(config, proxy)
    tray = TrayManager.create_default(
        TrayActions(
            lambda: holder["controller"].toggle_panel(),
            lambda: holder["controller"].refresh(),
            lambda: holder["controller"].quit(),
        )
    )
    controller = ApplicationController(
        config=config,
        warp=WarpService(runner),
        icons=IconRenderer(
            runtime_asset_path("cloudflare-template.svg"), _cache_dir()
        ),
        autostart=AutostartService(),
        diagnostics=DiagnosticsService(runner),
        tasks=BackgroundTasks(GLib.idle_add),
        scheduler=PeriodicScheduler(GLib.timeout_add_seconds, GLib.source_remove),
        window=window,
        tray=tray,
        logger=logger,
        quit_mainloop=Gtk.main_quit,
    )
    holder["controller"] = controller
    return controller, Gtk


def _action_proxy(holder: dict) -> UIActions:
    def call(name: str):
        return lambda *args: getattr(holder["controller"], name)(*args)

    return UIActions(
        on_toggle_connection=call("toggle_connection"),
        on_add_host=call("add_host"),
        on_remove_host=call("remove_host"),
        on_theme_changed=call("set_theme"),
        on_color_changed=call("set_state_color"),
        on_accent_changed=call("set_accent"),
        on_reset_appearance=call("reset_appearance"),
        on_autostart_changed=call("set_autostart"),
        on_auto_update_changed=call("set_auto_update"),
        on_interval_changed=call("set_update_interval"),
        on_mode_changed=call("set_mode"),
        on_protocol_changed=call("set_protocol"),
        on_restart_service=call("restart_service"),
        on_test_connection=call("check_connectivity"),
        on_open_log=call("open_log"),
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Control gráfico de Cloudflare WARP")
    parser.add_argument("--background", action="store_true")
    options = parser.parse_args(argv)
    config = Config.load()
    try:
        controller, gtk = _build_runtime(config)
    except Exception as error:
        print(f"No se pudo iniciar WARP Control: {error}", file=sys.stderr)
        return 1
    try:
        controller.start(background=options.background)
        gtk.main()
    finally:
        controller.shutdown()
    return 0
