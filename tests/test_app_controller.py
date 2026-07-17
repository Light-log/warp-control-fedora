from copy import deepcopy
from pathlib import Path

import warp_control.app as app_module
import pytest

from warp_control.config import Config
from warp_control.models import (
    HostsResult,
    OperationResult,
    ValueResult,
    WarpCapabilities,
    WarpState,
    WarpStatus,
)
from warp_control.app import ApplicationController, RefreshSnapshot


class FakeTasks:
    def __init__(self):
        self.pending = []

    def submit(self, worker, on_success, on_error=None):
        self.pending.append((worker, on_success, on_error))
        return object()

    def complete_next(self):
        worker, success, error = self.pending.pop(0)
        try:
            success(worker())
        except Exception as exc:
            if error is None:
                raise
            error(exc)


class FakeScheduler:
    def __init__(self):
        self.started = []
        self.stops = 0

    def start(self, callback, interval):
        self.started.append((callback, interval))

    def stop(self):
        self.stops += 1


class FakeWindow:
    def __init__(self):
        self.states = []
        self.hosts = []
        self.capabilities = []
        self.connection_settings = []
        self.configs = []
        self.visible = False

    def apply_state(self, state, icon_path=None):
        self.states.append((state, icon_path))

    def set_hosts(self, hosts):
        self.hosts.append(tuple(hosts))

    def set_capabilities(self, capabilities, mode=None, protocol=None):
        self.capabilities.append((capabilities, mode, protocol))

    def apply_connection_settings(self, mode, protocol):
        self.connection_settings.append((mode, protocol))

    def apply_config(self, config):
        self.configs.append(deepcopy(config))

    def get_visible(self):
        return self.visible

    def hide(self):
        self.visible = False

    def show_all(self):
        self.visible = True

    def present(self):
        self.visible = True


class FakeWarp:
    def __init__(self):
        self.state = WarpState.CONNECTED
        self.calls = []
        self.mode = "warp"
        self.protocol = "MASQUE"
        self.fail_mode = False

    def status(self):
        self.calls.append("status")
        return WarpStatus(True, "", 0, self.state)

    def list_hosts(self):
        self.calls.append("hosts")
        return HostsResult(True, "", 0, ("example.com",))

    def capabilities(self):
        self.calls.append("capabilities")
        return WarpCapabilities(True, ("warp", "doh"), ("MASQUE",), "remove", "")

    def get_mode(self):
        return ValueResult(True, "", 0, self.mode)

    def get_protocol(self):
        return ValueResult(True, "", 0, self.protocol)

    def connect(self):
        self.calls.append("connect")
        return OperationResult(True, "", 0)

    def disconnect(self):
        self.calls.append("disconnect")
        return OperationResult(True, "", 0)

    def add_host(self, host):
        self.calls.append(("add", host))
        return OperationResult(True, "", 0)

    def remove_host(self, host):
        self.calls.append(("remove", host))
        return OperationResult(True, "", 0)

    def set_mode(self, mode):
        self.calls.append(("mode", mode))
        if self.fail_mode:
            return OperationResult(False, "failed", 1)
        self.mode = mode
        return OperationResult(True, "", 0)

    def set_protocol(self, protocol):
        self.calls.append(("protocol", protocol))
        self.protocol = protocol
        return OperationResult(True, "", 0)


class FakeIcons:
    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.calls = []

    def render(self, state, config):
        self.calls.append((state, config.accent))
        return self.tmp_path / f"{state.value}.svg"


class FakeTray:
    def __init__(self):
        self.started = []
        self.updated = []
        self.closed = 0

    def start(self, path):
        self.started.append(Path(path))
        return True

    def update_icon(self, path):
        self.updated.append(Path(path))
        return True

    def close(self):
        self.closed += 1


class FakeAutostart:
    def __init__(self):
        self.calls = []
        self.enabled = False
        self.fail = False

    def enable(self):
        self.calls.append("enable")
        if self.fail:
            raise OSError("private-host.example/user-id-42")
        self.enabled = True

    def disable(self):
        self.calls.append("disable")
        self.enabled = False

    def is_enabled(self):
        return self.enabled


class FakeDiagnostics:
    def restart_service(self):
        return OperationResult(True, "", 0)

    def check_connectivity(self):
        return OperationResult(True, "", 0)

    def open_log(self):
        return OperationResult(True, "", 0)


def make_controller(tmp_path):
    config = Config(path=tmp_path / "config.json")
    tasks = FakeTasks()
    scheduler = FakeScheduler()
    window = FakeWindow()
    warp = FakeWarp()
    tray = FakeTray()
    controller = ApplicationController(
        config=config,
        warp=warp,
        icons=FakeIcons(tmp_path),
        autostart=FakeAutostart(),
        diagnostics=FakeDiagnostics(),
        tasks=tasks,
        scheduler=scheduler,
        window=window,
        tray=tray,
    )
    return controller, config, tasks, scheduler, window, warp, tray


def test_refresh_is_exclusive_and_applies_one_coherent_snapshot(tmp_path):
    controller, _config, tasks, _scheduler, window, warp, tray = make_controller(
        tmp_path
    )

    assert controller.refresh() is True
    assert controller.refresh() is False
    assert len(tasks.pending) == 1
    tasks.complete_next()

    assert controller.refreshing is False
    assert warp.calls == ["status", "hosts", "capabilities"]
    assert window.states[-1][0] is WarpState.CONNECTED
    assert window.hosts[-1] == ("example.com",)
    assert window.capabilities[-1][1:] == ("warp", "MASQUE")
    assert tray.updated[-1].name == "connected.svg"


def test_auto_update_switch_and_interval_persist_and_reschedule(tmp_path):
    controller, config, _tasks, scheduler, window, *_rest = make_controller(tmp_path)

    controller.start(background=True)
    assert scheduler.started[-1][1] == 5

    controller.set_auto_update(False)
    assert scheduler.stops >= 1
    assert config.auto_update_enabled is False

    controller.set_update_interval(12)
    controller.set_auto_update(True)
    assert scheduler.started[-1][1] == 12
    assert Config.load(config.path).update_interval_seconds == 12
    assert window.configs[-1].auto_update_enabled is True


def test_first_start_installs_default_autostart_without_disabling_opt_out(tmp_path):
    controller, _config, _tasks, _scheduler, _window, *_rest = make_controller(
        tmp_path
    )
    controller.start(background=True)
    controller.start(background=True)
    assert controller.autostart.calls == ["enable"]

    controller2, config2, _tasks, _scheduler, _window, *_rest = make_controller(
        tmp_path / "opt-out"
    )
    config2.autostart_enabled = False
    controller2.start(background=True)
    assert controller2.autostart.calls == []


def test_failed_startup_autostart_sync_reflects_actual_disabled_state(tmp_path):
    controller, config, _tasks, _scheduler, window, *_rest = make_controller(
        tmp_path
    )
    controller.autostart.fail = True

    controller.start(background=True)

    assert config.autostart_enabled is False
    assert Config.load(config.path).autostart_enabled is False
    assert window.configs[-1].autostart_enabled is False


def test_ui_actions_connect_all_mutations_and_host_expansion(tmp_path):
    controller, config, tasks, _scheduler, _window, warp, _tray = make_controller(
        tmp_path
    )
    actions = controller.ui_actions()

    actions.on_add_host("https://Example.com/path", True)
    tasks.complete_next()
    assert ("add", "example.com") in warp.calls
    assert ("add", "*.example.com") in warp.calls

    actions.on_theme_changed("light")
    actions.on_accent_changed("#123456")
    actions.on_color_changed("connected", "primary", "#654321")
    assert config.theme == "light"
    assert config.accent == "#123456"
    assert config.colors["connected"]["primary"] == "#654321"


def test_failed_mode_change_restores_previous_ui_selection(tmp_path):
    controller, _config, tasks, _scheduler, window, warp, _tray = make_controller(
        tmp_path
    )
    warp.fail_mode = True

    controller.set_mode("doh")
    tasks.complete_next()

    assert window.connection_settings[-1] == ("warp", "MASQUE")


def test_connection_action_uses_current_state_and_refreshes_after_completion(tmp_path):
    controller, _config, tasks, _scheduler, window, warp, tray = make_controller(
        tmp_path
    )
    controller._apply_snapshot(  # establish the displayed state
        RefreshSnapshot(
            warp.status(), warp.list_hosts(), warp.capabilities(), "warp", "MASQUE"
        )
    )

    controller.toggle_connection()
    assert window.states[-1][0] is WarpState.CONNECTING
    assert window.states[-1][1].name == "connecting.svg"
    assert tray.updated[-1].name == "connecting.svg"
    tasks.complete_next()
    assert "disconnect" in warp.calls
    assert len(tasks.pending) == 1


def test_shutdown_cancels_scheduler_and_closes_tray_once(tmp_path):
    controller, *_prefix, scheduler, _window, _warp, tray = make_controller(tmp_path)
    controller.shutdown()
    controller.shutdown()
    assert scheduler.stops == 1
    assert tray.closed == 1


def test_cli_bootstrap_is_injectable_and_always_shuts_down(monkeypatch, tmp_path):
    events = []

    class FakeController:
        def start(self, *, background=False):
            events.append(("start", background))

        def shutdown(self):
            events.append(("shutdown",))

    class FakeGtk:
        @staticmethod
        def main():
            events.append(("main",))

    monkeypatch.setattr(
        app_module.Config, "load", lambda: Config(path=tmp_path / "config.json")
    )
    monkeypatch.setattr(
        app_module,
        "_build_runtime",
        lambda _config: (FakeController(), FakeGtk),
    )

    assert app_module.main(["--background"]) == 0
    assert events == [("start", True), ("main",), ("shutdown",)]


def test_real_smoke_test_is_headless_and_does_not_probe_system_services(
    monkeypatch,
):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    assert app_module.run_smoke_test() == 0


def test_cli_smoke_test_bypasses_gtk_runtime(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "_build_runtime",
        lambda _config: (_ for _ in ()).throw(AssertionError("GTK used")),
    )
    assert app_module.main(["--smoke-test"]) == 0


def test_cli_help_exits_zero_without_building_runtime(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "_build_runtime",
        lambda _config: (_ for _ in ()).throw(AssertionError("runtime used")),
    )
    with pytest.raises(SystemExit) as exit_info:
        app_module.main(["--help"])
    assert exit_info.value.code == 0


def test_cli_runtime_error_still_shuts_down(monkeypatch, tmp_path, capsys):
    events = []

    class BrokenController:
        def start(self, *, background=False):
            raise RuntimeError("secret.example/device-123")

        def shutdown(self):
            events.append("shutdown")

    class FakeGtk:
        @staticmethod
        def main():
            raise AssertionError("unreachable")

    monkeypatch.setattr(
        app_module.Config, "load", lambda: Config(path=tmp_path / "config.json")
    )
    monkeypatch.setattr(
        app_module, "_build_runtime", lambda _config: (BrokenController(), FakeGtk)
    )

    assert app_module.main([]) == 1
    assert events == ["shutdown"]
    assert "secret.example" not in capsys.readouterr().err


def test_controller_logs_only_structured_result_metadata(tmp_path):
    class RecordingLogger:
        def __init__(self):
            self.records = []

        def info(self, message, *args):
            self.records.append((message, args))

        def error(self, message, *args):
            self.records.append((message, args))

        def warning(self, message, *args):
            self.records.append((message, args))

    controller, *_rest = make_controller(tmp_path)
    logger = RecordingLogger()
    controller.logger = logger
    secret = "customer.example/device-id-42 token=private"

    controller._log_result("operation", OperationResult(False, secret, 7))
    controller._operation_failed(RuntimeError(secret))

    serialized = repr(logger.records)
    assert "customer.example" not in serialized
    assert "device-id-42" not in serialized
    assert "private" not in serialized
    assert "returncode" in serialized
