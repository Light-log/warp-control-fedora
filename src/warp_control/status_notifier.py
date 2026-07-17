"""StatusNotifierItem implementation with an injectable D-Bus adapter."""

import os
from pathlib import Path
from typing import Any, Callable, Optional, Tuple, Union


ITEM_INTERFACE = "org.kde.StatusNotifierItem"
ITEM_PATH = "/StatusNotifierItem"
WATCHER_BUS_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
WATCHER_INTERFACE = "org.kde.StatusNotifierWatcher"

INTROSPECTION_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <method name="ContextMenu"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Activate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <signal name="NewIcon"/>
  </interface>
</node>
""".strip()


class StatusNotifierItem:
    """Publish a state icon and compact-panel actions through StatusNotifierItem."""

    def __init__(
        self,
        bus: Any,
        toggle_panel: Callable[[], None],
        show_context_menu: Callable[[int, int], None],
        icon_path: Union[Path, str],
        *,
        service_name: Optional[str] = None,
    ) -> None:
        self._bus = bus
        self._toggle_panel = toggle_panel
        self._show_context_menu = show_context_menu
        self._icon_path = Path(icon_path).expanduser().resolve(strict=False)
        self._service_name = service_name or (
            "org.kde.StatusNotifierItem.warp_control_{}".format(os.getpid())
        )
        self._registration_id: Optional[int] = None
        self._owner_id: Optional[int] = None
        self._started = False

    def start(self) -> bool:
        if self._started:
            return True
        try:
            if not self._bus.watcher_available():
                return False
            self._registration_id = self._bus.export(
                ITEM_PATH,
                INTROSPECTION_XML,
                self._handle_method,
                self._get_property,
            )
            self._owner_id = self._bus.own_name(self._service_name)
            self._bus.register_item(self._service_name)
        except Exception:
            self.close()
            return False
        self._started = True
        return True

    def _handle_method(self, method_name: str, parameters: Tuple[int, int]) -> None:
        x, y = parameters
        if method_name in ("Activate", "SecondaryActivate"):
            self._toggle_panel()
        elif method_name == "ContextMenu":
            self._show_context_menu(int(x), int(y))

    def _get_property(self, property_name: str) -> Any:
        properties = {
            "Category": "ApplicationStatus",
            "Id": "warp-control",
            "Title": "WARP Control",
            "Status": "Active",
            "IconName": self._icon_path.stem,
            "IconThemePath": str(self._icon_path.parent),
            "ItemIsMenu": False,
        }
        if property_name not in properties:
            raise KeyError(property_name)
        return properties[property_name]

    def update_icon(self, icon_path: Union[Path, str]) -> None:
        self._icon_path = Path(icon_path).expanduser().resolve(strict=False)
        if self._started:
            self._bus.emit_signal(ITEM_PATH, ITEM_INTERFACE, "NewIcon")

    def close(self) -> None:
        registration_id, self._registration_id = self._registration_id, None
        owner_id, self._owner_id = self._owner_id, None
        self._started = False
        if registration_id is not None:
            try:
                self._bus.unexport(registration_id)
            except Exception:
                pass
        if owner_id is not None:
            try:
                self._bus.unown_name(owner_id)
            except Exception:
                pass


class GioSessionBus:
    """Small Gio.DBus adapter; the application logic above stays unit-testable."""

    def __init__(self, connection: Any, gio: Any, glib: Any) -> None:
        self._connection = connection
        self._gio = gio
        self._glib = glib
        self._node_info = None

    @classmethod
    def connect(cls) -> "GioSessionBus":
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib

        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        return cls(connection, Gio, GLib)

    def watcher_available(self) -> bool:
        result = self._connection.call_sync(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "NameHasOwner",
            self._glib.Variant("(s)", (WATCHER_BUS_NAME,)),
            self._glib.VariantType.new("(b)"),
            self._gio.DBusCallFlags.NONE,
            -1,
            None,
        )
        return bool(result.unpack()[0])

    def export(self, path, xml, method_handler, property_handler):
        self._node_info = self._gio.DBusNodeInfo.new_for_xml(xml)
        interface_info = self._node_info.interfaces[0]

        def on_method_call(
            _connection,
            _sender,
            _object_path,
            _interface_name,
            method_name,
            parameters,
            invocation,
        ):
            try:
                method_handler(method_name, tuple(parameters.unpack()))
                invocation.return_value(None)
            except Exception as error:
                invocation.return_dbus_error(
                    "org.kde.StatusNotifierItem.Error", str(error)
                )

        def on_get_property(
            _connection,
            _sender,
            _object_path,
            _interface_name,
            property_name,
        ):
            value = property_handler(property_name)
            signature = "b" if isinstance(value, bool) else "s"
            return self._glib.Variant(signature, value)

        return self._connection.register_object(
            path, interface_info, on_method_call, on_get_property, None
        )

    def own_name(self, name):
        return self._gio.bus_own_name_on_connection(
            self._connection, name, self._gio.BusNameOwnerFlags.NONE, None, None
        )

    def register_item(self, service):
        self._connection.call_sync(
            WATCHER_BUS_NAME,
            WATCHER_PATH,
            WATCHER_INTERFACE,
            "RegisterStatusNotifierItem",
            self._glib.Variant("(s)", (service,)),
            None,
            self._gio.DBusCallFlags.NONE,
            -1,
            None,
        )

    def emit_signal(self, path, interface, signal, parameters=None):
        self._connection.emit_signal(None, path, interface, signal, parameters)

    def unexport(self, registration_id):
        self._connection.unregister_object(registration_id)

    def unown_name(self, owner_id):
        self._gio.bus_unown_name(owner_id)
