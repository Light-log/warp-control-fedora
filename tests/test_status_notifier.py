import re
from pathlib import Path

from warp_control.app_indicator import AppIndicatorFallback, NativeContextMenu
from warp_control.status_notifier import StatusNotifierItem
from warp_control.tray import TrayActions, TrayManager


class FakeBus:
    def __init__(self, watcher: bool = True, auto_acquire: bool = True) -> None:
        self.watcher = watcher
        self.auto_acquire = auto_acquire
        self.exported = []
        self.owned = []
        self.calls = []
        self.signals = []
        self.unexports = []
        self.unowns = []
        self.method_handler = None
        self.property_handler = None
        self.acquired = None
        self.lost = None

    def watcher_available(self) -> bool:
        return self.watcher

    def export(self, path, xml, method_handler, property_handler):
        self.exported.append((path, xml))
        self.method_handler = method_handler
        self.property_handler = property_handler
        return 41

    def own_name(self, name, acquired, lost):
        self.owned.append(name)
        self.acquired = acquired
        self.lost = lost
        if self.auto_acquire:
            acquired(name)
        return 42

    def acquire_name(self):
        self.acquired(self.owned[-1])

    def lose_name(self):
        self.lost(self.owned[-1])

    def register_item(self, service):
        self.calls.append(service)

    def emit_signal(self, path, interface, signal, parameters=None):
        self.signals.append((path, interface, signal, parameters))

    def unexport(self, registration_id):
        self.unexports.append(registration_id)

    def unown_name(self, owner_id):
        self.unowns.append(owner_id)


def test_status_notifier_exports_and_registers_with_watcher(tmp_path):
    bus = FakeBus()
    icon = tmp_path / "warp-control-connected.svg"
    icon.write_text("<svg/>", encoding="utf-8")

    item = StatusNotifierItem(bus, lambda: None, lambda _x, _y: None, icon)

    assert item.start() is True
    assert bus.exported[0][0] == "/StatusNotifierItem"
    assert "org.kde.StatusNotifierItem" in bus.exported[0][1]
    assert bus.calls == [bus.owned[0]]
    assert bus.property_handler("IconName") == "warp-control-connected"
    assert bus.property_handler("IconThemePath") == str(tmp_path)
    assert re.fullmatch(r"org\.kde\.StatusNotifierItem-\d+-\d+", bus.owned[0])


def test_watcher_registration_waits_until_bus_name_is_acquired(tmp_path):
    bus = FakeBus(auto_acquire=False)
    item = StatusNotifierItem(
        bus, lambda: None, lambda _x, _y: None, tmp_path / "state.svg"
    )

    assert item.start() is True
    assert bus.calls == []

    bus.acquire_name()

    assert bus.calls == [bus.owned[0]]


def test_name_loss_closes_item_and_reports_unavailability(tmp_path):
    unavailable = []
    bus = FakeBus()
    item = StatusNotifierItem(
        bus, lambda: None, lambda _x, _y: None, tmp_path / "state.svg"
    )
    item.set_unavailable_callback(lambda: unavailable.append(True))
    item.start()

    bus.lose_name()

    assert unavailable == [True]
    assert bus.unexports == [41]
    assert bus.unowns == [42]


def test_activate_toggles_panel_and_context_menu_uses_coordinates(tmp_path):
    activated = []
    context = []
    bus = FakeBus()
    item = StatusNotifierItem(
        bus,
        lambda: activated.append(True),
        lambda x, y: context.append((x, y)),
        tmp_path / "state.svg",
    )
    item.start()

    bus.method_handler("Activate", (10, 20))
    bus.method_handler("ContextMenu", (30, 40))

    assert activated == [True]
    assert context == [(30, 40)]


def test_update_icon_publishes_exact_rendered_svg_and_emits_changes(tmp_path):
    bus = FakeBus()
    first = tmp_path / "warp-control-disconnected.svg"
    second = tmp_path / "warp-control-connecting.svg"
    item = StatusNotifierItem(bus, lambda: None, lambda _x, _y: None, first)
    item.start()

    item.update_icon(second)

    assert bus.property_handler("IconName") == second.stem
    assert bus.property_handler("IconThemePath") == str(second.parent)
    assert [signal[2] for signal in bus.signals] == ["NewIcon"]


def test_status_notifier_declines_start_without_watcher(tmp_path):
    bus = FakeBus(watcher=False)
    item = StatusNotifierItem(bus, lambda: None, lambda _x, _y: None, tmp_path / "x.svg")

    assert item.start() is False
    assert bus.exported == []
    assert bus.owned == []


def test_status_notifier_declines_start_when_watcher_probe_fails(tmp_path):
    class BrokenBus(FakeBus):
        def watcher_available(self):
            raise RuntimeError("session bus disappeared")

    item = StatusNotifierItem(
        BrokenBus(), lambda: None, lambda _x, _y: None, tmp_path / "x.svg"
    )

    assert item.start() is False


def test_status_notifier_cleanup_is_idempotent(tmp_path):
    bus = FakeBus()
    item = StatusNotifierItem(bus, lambda: None, lambda _x, _y: None, tmp_path / "x.svg")
    item.start()

    item.close()
    item.close()

    assert bus.unexports == [41]
    assert bus.unowns == [42]


def test_partial_registration_is_rolled_back(tmp_path):
    class BrokenRegistrationBus(FakeBus):
        def register_item(self, service):
            raise RuntimeError(service)

    bus = BrokenRegistrationBus()
    item = StatusNotifierItem(
        bus, lambda: None, lambda _x, _y: None, tmp_path / "x.svg"
    )

    assert item.start() is False
    assert bus.unexports == [41]
    assert bus.unowns == [42]


def test_asynchronous_watcher_registration_failure_reports_unavailable(tmp_path):
    class BrokenRegistrationBus(FakeBus):
        def register_item(self, service):
            raise RuntimeError(service)

    unavailable = []
    bus = BrokenRegistrationBus(auto_acquire=False)
    item = StatusNotifierItem(
        bus, lambda: None, lambda _x, _y: None, tmp_path / "x.svg"
    )
    item.set_unavailable_callback(lambda: unavailable.append(True))
    assert item.start() is True

    bus.acquire_name()

    assert unavailable == [True]
    assert bus.unexports == [41]
    assert bus.unowns == [42]


def test_cleanup_attempts_name_release_when_unexport_fails(tmp_path):
    class BrokenCleanupBus(FakeBus):
        def unexport(self, registration_id):
            self.unexports.append(registration_id)
            raise RuntimeError("already gone")

    bus = BrokenCleanupBus()
    item = StatusNotifierItem(
        bus, lambda: None, lambda _x, _y: None, tmp_path / "x.svg"
    )
    item.start()

    item.close()

    assert bus.unexports == [41]
    assert bus.unowns == [42]


class FakeWidget:
    def __init__(self, label=None):
        self.label = label
        self.callbacks = {}

    def connect(self, signal, callback):
        self.callbacks[signal] = callback

    def show_all(self):
        pass


class FakeMenu(FakeWidget):
    def __init__(self):
        super().__init__()
        self.children = []

    def append(self, item):
        self.children.append(item)

    def popup_at_pointer(self, event):
        self.popup_event = event


class FakeGtk:
    Menu = FakeMenu
    MenuItem = FakeWidget


class FakeIndicator:
    def __init__(self):
        self.status = None
        self.menu = None
        self.theme_path = None
        self.icon = None

    def set_status(self, status):
        self.status = status

    def set_menu(self, menu):
        self.menu = menu

    def set_icon_theme_path(self, path):
        self.theme_path = path

    def set_icon_full(self, icon, description):
        self.icon = (icon, description)


class FakeIndicatorModule:
    class IndicatorStatus:
        ACTIVE = "active"

    class IndicatorCategory:
        APPLICATION_STATUS = "application"

    class Indicator:
        instance = None

        @classmethod
        def new(cls, _identifier, _icon, _category):
            cls.instance = FakeIndicator()
            return cls.instance


def test_app_indicator_fallback_has_only_native_expected_menu_items(tmp_path):
    actions = []
    fallback = AppIndicatorFallback(
        FakeGtk,
        FakeIndicatorModule,
        TrayActions(
            toggle_panel=lambda: actions.append("open"),
            refresh=lambda: actions.append("refresh"),
            quit=lambda: actions.append("quit"),
        ),
    )
    icon = tmp_path / "warp-control-connected.svg"

    assert fallback.start(icon) is True
    indicator = FakeIndicatorModule.Indicator.instance
    assert [item.label for item in indicator.menu.children] == [
        "Abrir panel",
        "Actualizar",
        "Salir",
    ]
    assert all(type(item) is FakeWidget for item in indicator.menu.children)
    indicator.menu.children[0].callbacks["activate"](indicator.menu.children[0])
    assert actions == ["open"]
    assert indicator.theme_path == str(tmp_path)
    assert indicator.icon[0] == icon.stem


def test_native_context_menu_has_actions_and_uses_gtk_popup():
    actions = []
    menu = NativeContextMenu(
        FakeGtk,
        TrayActions(
            toggle_panel=lambda: actions.append("open"),
            refresh=lambda: actions.append("refresh"),
            quit=lambda: actions.append("quit"),
        ),
    )

    menu.show(20, 30)
    menu.widget.children[1].callbacks["activate"](menu.widget.children[1])

    assert [item.label for item in menu.widget.children] == [
        "Abrir panel",
        "Actualizar",
        "Salir",
    ]
    assert menu.widget.popup_event is None
    assert actions == ["refresh"]


class FakeBackend:
    def __init__(self, started):
        self.started = started
        self.updated = []
        self.closed = 0

    def start(self, *_args):
        return self.started

    def update_icon(self, path):
        self.updated.append(Path(path))

    def close(self):
        self.closed += 1


def test_tray_uses_fallback_only_when_status_notifier_is_unavailable(tmp_path):
    notifier = FakeBackend(False)
    fallback = FakeBackend(True)
    tray = TrayManager(lambda _icon: notifier, lambda: fallback)

    assert tray.start(tmp_path / "initial.svg") is True
    tray.update_icon(tmp_path / "changed.svg")
    tray.close()
    tray.close()

    assert fallback.updated == [tmp_path / "changed.svg"]
    assert fallback.closed == 1
    assert notifier.closed == 1


def test_tray_does_not_create_fallback_when_status_notifier_starts(tmp_path):
    notifier = FakeBackend(True)
    fallback_created = []
    tray = TrayManager(
        lambda _icon: notifier,
        lambda: fallback_created.append(True),
    )

    assert tray.start(tmp_path / "initial.svg") is True
    assert fallback_created == []


def test_tray_start_is_idempotent_without_leaking_notifier(tmp_path):
    created = []

    def factory(_icon):
        backend = FakeBackend(True)
        created.append(backend)
        return backend

    tray = TrayManager(factory, lambda: FakeBackend(True))

    assert tray.start(tmp_path / "initial.svg") is True
    assert tray.start(tmp_path / "changed.svg") is True

    assert len(created) == 1
    assert created[0].updated == [tmp_path / "changed.svg"]


def test_tray_start_is_idempotent_after_selecting_fallback(tmp_path):
    fallback = FakeBackend(True)
    tray = TrayManager(lambda _icon: FakeBackend(False), lambda: fallback)

    assert tray.start(tmp_path / "initial.svg") is True
    assert tray.start(tmp_path / "changed.svg") is True

    assert fallback.updated == [tmp_path / "changed.svg"]


def test_status_notifier_name_loss_activates_tray_fallback(tmp_path):
    bus = FakeBus()
    fallback = FakeBackend(True)
    tray = TrayManager(
        lambda icon: StatusNotifierItem(
            bus, lambda: None, lambda _x, _y: None, icon
        ),
        lambda: fallback,
    )
    tray.start(tmp_path / "initial.svg")

    bus.lose_name()

    assert tray.active_backend is fallback


class ExplodingBackend(FakeBackend):
    def __init__(self, *, start=False, update=False, close=False):
        super().__init__(True)
        self.explode_start = start
        self.explode_update = update
        self.explode_close = close

    def start(self, *_args):
        if self.explode_start:
            raise RuntimeError("start")
        return True

    def update_icon(self, path):
        if self.explode_update:
            raise RuntimeError("update")
        super().update_icon(path)

    def close(self):
        self.closed += 1
        if self.explode_close:
            raise RuntimeError("close")


def test_tray_degrades_to_fallback_when_notifier_update_raises(tmp_path):
    notifier = ExplodingBackend(update=True, close=True)
    fallback = FakeBackend(True)
    tray = TrayManager(lambda _icon: notifier, lambda: fallback)
    tray.start(tmp_path / "initial.svg")

    assert tray.update_icon(tmp_path / "changed.svg") is True

    assert fallback.updated == []
    assert notifier.closed == 1
    assert tray.active_backend is fallback


def test_tray_contains_backend_start_update_and_close_failures(tmp_path):
    notifier = ExplodingBackend(start=True, close=True)
    fallback = ExplodingBackend(start=True, close=True)
    tray = TrayManager(lambda _icon: notifier, lambda: fallback)

    assert tray.start(tmp_path / "initial.svg") is False
    assert tray.update_icon(tmp_path / "changed.svg") is False
    tray.close()
    tray.close()

    assert tray.active_backend is None
