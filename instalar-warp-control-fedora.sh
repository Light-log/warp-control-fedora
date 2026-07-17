#!/usr/bin/env bash
set -Eeuo pipefail

# ============================================================
#  WARP Control — instalador todo-en-uno para Fedora
# ------------------------------------------------------------
#  Una interfaz pequeña y bonita para Cloudflare WARP:
#   • Icono en la barra de tareas (bandeja del sistema)
#   • Saber al instante si la VPN está activa o no
#   • Conectar / desconectar con un clic
#   • Excluir URLs/dominios para que NO pasen por la VPN
#   • Panel de Apariencia para cambiar los colores del icono
#
#  Todo (app de Python + icono SVG + dependencias) va dentro
#  de este único archivo .sh ejecutable.
#
#  Uso:        ./instalar-warp-control-fedora.sh
#  Desinstalar: ./instalar-warp-control-fedora.sh --uninstall
# ============================================================

APP_NAME="WARP Control"
APP_ID="com.robler.warpcontrol"
APP_DIR="$HOME/.local/lib/warp-control"
APP_SCRIPT="$APP_DIR/warp_control.py"
ICON_DIR="$APP_DIR/icons"
CONFIG_DIR="$HOME/.config/warp-control"
BIN_DIR="$HOME/.local/bin"
BIN_FILE="$BIN_DIR/warp-control"
DESKTOP_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$DESKTOP_DIR/warp-control.desktop"
AUTOSTART_DIR="$HOME/.config/autostart"
AUTOSTART_FILE="$AUTOSTART_DIR/warp-control.desktop"
LOG_FILE="$HOME/.local/state/warp-control/warp-control.log"

c_blue='\033[1;34m'; c_green='\033[1;32m'; c_yellow='\033[1;33m'; c_red='\033[1;31m'; c_off='\033[0m'
info()  { printf "${c_blue}[INFO]${c_off} %s\n" "$*"; }
ok()    { printf "${c_green}[OK]${c_off} %s\n" "$*"; }
warn()  { printf "${c_yellow}[AVISO]${c_off} %s\n" "$*"; }
error() { printf "${c_red}[ERROR]${c_off} %s\n" "$*" >&2; }

cleanup_error() {
    error "La instalación se detuvo en la línea $1."
    error "Revisa los mensajes anteriores y vuelve a ejecutar el archivo."
}
trap 'cleanup_error $LINENO' ERR

if [[ "${EUID}" -eq 0 ]]; then
    error "No ejecutes este archivo directamente como root."
    echo "Úsalo así: ./$(basename "$0")"
    echo "El instalador pedirá sudo solo cuando sea necesario."
    exit 1
fi

uninstall_app() {
    info "Cerrando WARP Control…"
    pkill -f "$APP_SCRIPT" 2>/dev/null || true
    rm -rf "$APP_DIR"
    rm -f "$BIN_FILE" "$DESKTOP_FILE" "$AUTOSTART_FILE"
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
    ok "WARP Control fue eliminado. (Tu configuración en $CONFIG_DIR se conserva.)"
    ok "Cloudflare WARP permanece instalado en el sistema."
}

if [[ "${1:-}" == "--uninstall" ]]; then
    uninstall_app
    exit 0
fi

if [[ ! -r /etc/os-release ]]; then
    error "No se pudo identificar la distribución Linux."
    exit 1
fi

# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "fedora" && "${ID_LIKE:-}" != *"fedora"* ]]; then
    warn "Este instalador fue diseñado para Fedora. Sistema detectado: ${PRETTY_NAME:-desconocido}"
    read -r -p "¿Deseas continuar de todas formas? [s/N]: " answer
    [[ "$answer" =~ ^[sS]$ ]] || exit 1
fi

info "Solicitando permisos administrativos para instalar dependencias…"
sudo -v

info "Instalando dependencias gráficas…"
sudo dnf install -y \
    curl \
    python3 \
    python3-gobject \
    python3-cairo \
    gtk3 \
    libayatana-appindicator-gtk3 \
    gnome-shell-extension-appindicator \
    librsvg2 \
    desktop-file-utils
ok "Dependencias instaladas."

if ! command -v warp-cli >/dev/null 2>&1; then
    info "Cloudflare WARP no está instalado. Añadiendo el repositorio oficial…"
    sudo curl -fsSL \
        https://pkg.cloudflareclient.com/cloudflare-warp-ascii.repo \
        -o /etc/yum.repos.d/cloudflare-warp.repo

    info "Instalando el paquete cloudflare-warp…"
    if ! sudo dnf install -y cloudflare-warp; then
        error "Fedora no pudo instalar cloudflare-warp desde el repositorio oficial."
        error "Comprueba que tu arquitectura tenga un paquete compatible en pkg.cloudflareclient.com."
        exit 1
    fi
else
    ok "Cloudflare WARP ya estaba instalado."
fi

info "Activando el servicio de WARP…"
sudo systemctl enable --now warp-svc

warp_cmd() {
    # Archivo temporal privado por invocación (evita symlink/race en /tmp).
    local log
    log="$(mktemp "${TMPDIR:-/tmp}/warp-control-command.XXXXXX")"

    if warp-cli --accept-tos "$@" >"$log" 2>&1; then
        cat "$log"
        rm -f "$log"
        return 0
    fi
    if grep -Eqi 'accept-tos.*(unknown|unexpected|unrecognized)' "$log"; then
        rm -f "$log"
        warp-cli "$@"
        return $?
    fi
    cat "$log" >&2
    rm -f "$log"
    return 1
}

if ! warp_cmd registration show >/dev/null 2>&1; then
    info "Registrando este equipo en 1.1.1.1 con WARP…"
    warp_cmd registration new
else
    ok "El equipo ya está registrado en WARP."
fi

info "Configurando WARP con DNS sobre HTTPS…"
if ! warp_cmd mode warp+doh >/dev/null 2>&1; then
    warn "La versión instalada no aceptó 'warp+doh'. Se intentará el modo 'warp'."
    warp_cmd mode warp >/dev/null 2>&1 || true
fi

info "Creando la aplicación y sus iconos…"
mkdir -p "$APP_DIR" "$ICON_DIR" "$CONFIG_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$AUTOSTART_DIR" "$(dirname "$LOG_FILE")"

cat > "$APP_SCRIPT" <<'__WARP_CONTROL_PYTHON__'
#!/usr/bin/env python3
"""Panel compacto y bonito para controlar Cloudflare WARP en Fedora."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

import gi

# Fijamos las versiones ANTES de importar. En Fedora reciente GTK 4 es el
# valor por defecto, así que si no pedimos Gdk/GdkPixbuf 3.x/2.x de forma
# explícita, Python cargaría Gdk 4.0 y chocaría con Gtk 3.0.
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GLib, Gtk, GdkPixbuf  # noqa: E402

try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator  # type: ignore  # noqa: E402
except (ValueError, ImportError):
    try:
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3 as AppIndicator  # type: ignore  # noqa: E402
    except (ValueError, ImportError):
        AppIndicator = None  # type: ignore

APP_ID = "com.robler.warpcontrol"
APP_NAME = "WARP Control"
APP_DIR = Path.home() / ".local" / "lib" / "warp-control"
ICON_DIR = APP_DIR / "icons"
CONFIG_DIR = Path.home() / ".config" / "warp-control"
CONFIG_FILE = CONFIG_DIR / "config.json"
AUTOSTART_FILE = Path.home() / ".config" / "autostart" / "warp-control.desktop"

# Estados -> nombre del archivo de icono (sin extensión) usado por el indicador.
ICONS = {
    "connected": "warp-control-connected",
    "disconnected": "warp-control-disconnected",
    "connecting": "warp-control-connecting",
    "error": "warp-control-error",
}

# Plantilla del icono Cloudflare. Los colores se inyectan según la configuración
# y se vuelve a dibujar cada vez que el usuario los cambia en "Apariencia".
ICON_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="128" height="128">'
    '<path d="M16.493 17.4c.135-.52.08-.983-.161-1.338-.215-.328-.592-.519-1.05-.519'
    'l-8.663-.109a.148.148 0 01-.135-.082c-.027-.054-.027-.109-.027-.163.027-.082.108-.164'
    '.189-.164l8.744-.11c1.05-.054 2.153-.9 2.556-1.937l.511-1.31c.027-.055.027-.11.027-.164'
    'C17.92 8.91 15.66 7 12.942 7c-2.503 0-4.628 1.638-5.381 3.903a2.432 2.432 0 00-1.803-.491'
    'c-1.21.109-2.153 1.092-2.287 2.32-.027.328 0 .628.054.9C1.56 13.688 0 15.326 0 17.319'
    'c0 .19.027.355.027.545 0 .082.08.137.161.137h15.983c.08 0 .188-.055.215-.164l.107-.437" '
    'fill="{primary}"/>'
    '<path d="M19.238 11.75h-.242c-.054 0-.108.054-.135.109l-.35 1.2c-.134.52-.08.983.162 1.338'
    '.215.328.592.518 1.05.518l1.855.11c.054 0 .108.027.135.082.027.054.027.109.027.163-.027.082'
    '-.108.164-.188.164l-1.91.11c-1.05.054-2.153.9-2.557 1.937l-.134.355c-.027.055.026.137.107.137'
    'h6.592c.081 0 .162-.055.162-.137.107-.41.188-.846.188-1.31-.027-2.62-2.153-4.777-4.762-4.777" '
    'fill="{secondary}"/>'
    '</svg>'
)

# Colores por defecto de cada estado (primario y secundario).
DEFAULT_COLORS = {
    "connected": {"primary": "#16A34A", "secondary": "#4ADE80"},
    "connecting": {"primary": "#F38020", "secondary": "#FCAD32"},
    "disconnected": {"primary": "#64748B", "secondary": "#94A3B8"},
    "error": {"primary": "#DC2626", "secondary": "#F87171"},
}
DEFAULT_ACCENT = "#F38020"

STATE_LABELS = {
    "connected": "Conectado",
    "disconnected": "Desconectado",
    "connecting": "Conectando…",
    "unknown": "Estado desconocido",
    "error": "Error",
}
STATE_NAMES_ES = {
    "connected": "Conectado",
    "connecting": "Conectando",
    "disconnected": "Desconectado",
    "error": "Error",
}

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def icon_file(state: str) -> Path:
    return ICON_DIR / f"{ICONS.get(state, ICONS['disconnected'])}.svg"


# --------------------------------------------------------------------------- #
#  Configuración persistente
# --------------------------------------------------------------------------- #
class Config:
    """Carga y guarda los colores y preferencias del usuario."""

    def __init__(self) -> None:
        self.colors = {k: dict(v) for k, v in DEFAULT_COLORS.items()}
        self.accent = DEFAULT_ACCENT
        self.theme = "dark"  # "dark" o "light" (Windscribe usa oscuro por defecto)
        self.load()

    def load(self) -> None:
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        accent = data.get("accent")
        if isinstance(accent, str) and HEX_RE.match(accent):
            self.accent = accent.upper()
        theme = data.get("theme")
        if theme in ("dark", "light"):
            self.theme = theme
        colors = data.get("colors", {})
        for state, defaults in DEFAULT_COLORS.items():
            entry = colors.get(state, {})
            for key in ("primary", "secondary"):
                value = entry.get(key)
                if isinstance(value, str) and HEX_RE.match(value):
                    self.colors[state][key] = value.upper()

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"accent": self.accent, "theme": self.theme, "colors": self.colors}
        CONFIG_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def reset(self) -> None:
        self.colors = {k: dict(v) for k, v in DEFAULT_COLORS.items()}
        self.accent = DEFAULT_ACCENT

    def write_icons(self) -> None:
        """Genera los SVG de cada estado con los colores actuales."""
        ICON_DIR.mkdir(parents=True, exist_ok=True)
        for state, name in ICONS.items():
            colors = self.colors[state]
            svg = ICON_TEMPLATE.format(
                primary=colors["primary"], secondary=colors["secondary"]
            )
            (ICON_DIR / f"{name}.svg").write_text(svg, encoding="utf-8")


# --------------------------------------------------------------------------- #
#  Utilidades de URLs / warp-cli
# --------------------------------------------------------------------------- #
def normalize_host(value: str) -> str:
    """Convierte una URL pegada por el usuario en un nombre de host."""
    raw = value.strip()
    if not raw:
        raise ValueError("Escribe una URL o un dominio.")

    wildcard = raw.startswith("*.")
    if wildcard:
        raw = raw[2:]

    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    host = parsed.hostname
    if not host:
        raise ValueError("No se pudo obtener el dominio de la URL.")

    host = host.rstrip(".").lower()
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("El dominio contiene caracteres no válidos.") from exc

    if ":" not in host:
        labels = host.split(".")
        label_pattern = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
        if any(not label_pattern.fullmatch(label) for label in labels):
            raise ValueError("El dominio contiene caracteres no válidos.")

    return f"*.{host}" if wildcard else host


def run_process(command: list[str], timeout: int = 35) -> tuple[bool, str]:
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, env=env, check=False
        )
    except subprocess.TimeoutExpired:
        return False, "El comando tardó demasiado en responder."
    except OSError as exc:
        return False, f"No se pudo ejecutar el comando: {exc}"

    output = "\n".join(
        part.strip() for part in (result.stdout, result.stderr) if part and part.strip()
    ).strip()
    return result.returncode == 0, output


def run_warp(*args: str, timeout: int = 35) -> tuple[bool, str]:
    binary = shutil.which("warp-cli")
    if not binary:
        return False, "No se encontró warp-cli. Ejecuta nuevamente el instalador."

    ok, output = run_process([binary, "--accept-tos", *args], timeout)
    if ok:
        return True, output

    lower = output.lower()
    if "accept-tos" in lower and any(w in lower for w in ("unknown", "unexpected", "unrecognized")):
        return run_process([binary, *args], timeout)
    return False, output or "warp-cli terminó con un error."


def parse_status(output: str) -> str:
    text = output.lower()
    if "disconnected" in text:
        return "disconnected"
    if "connecting" in text or "reconnecting" in text:
        return "connecting"
    if "connected" in text:
        return "connected"
    return "unknown"


def parse_hosts(output: str) -> list[str]:
    hosts: list[str] = []
    for line in output.splitlines():
        value = line.strip().lstrip("-•").strip()
        if not value:
            continue
        if value.lower().startswith(("excluded host", "included host", "no excluded")):
            continue
        value = re.sub(r"\s+\([^)]*\)\s*$", "", value).strip()
        if " " in value:
            value = value.split()[0]
        try:
            host = normalize_host(value)
        except ValueError:
            continue
        if host not in hosts:
            hosts.append(host)
    return sorted(hosts)


def rgba_to_hex(rgba: Gdk.RGBA) -> str:
    return "#{:02X}{:02X}{:02X}".format(
        round(rgba.red * 255), round(rgba.green * 255), round(rgba.blue * 255)
    )


def hex_to_rgba(value: str) -> Gdk.RGBA:
    rgba = Gdk.RGBA()
    rgba.parse(value)
    return rgba


# --------------------------------------------------------------------------- #
#  Aplicación
# --------------------------------------------------------------------------- #
class WarpControl:
    def __init__(self) -> None:
        self.state = "unknown"
        self.busy = False
        self.status_running = False
        self.hosts_running = False
        self.color_buttons: dict[str, dict[str, Gtk.ColorButton]] = {}

        self.config = Config()
        self.config.write_icons()  # garantiza que los SVG existen y reflejan la config

        self.css_provider = Gtk.CssProvider()
        self._install_css()
        self._build_window()
        self._build_indicator()
        self.refresh_all()
        GLib.timeout_add_seconds(5, self._status_timer)

    # ---------------------------- estilo ---------------------------------- #
    def _palette(self) -> dict[str, str]:
        if self.config.theme == "dark":
            return {
                "bg": "#0e1726",
                "card": "#17223a",
                "border": "#243049",
                "text": "#e8ecf3",
                "muted": "#8893a8",
                "entry_bg": "#101a2c",
                "ghost_bg": "#243049",
                "ghost_text": "#cdd6e4",
                "ghost_hover": "#2c3a57",
                "pill_bg": "#101a2c",
            }
        return {
            "bg": "#f5f6f8",
            "card": "#ffffff",
            "border": "#e6e8ec",
            "text": "#1f2733",
            "muted": "#8a909a",
            "entry_bg": "#ffffff",
            "ghost_bg": "#eef1f5",
            "ghost_text": "#334155",
            "ghost_hover": "#e2e7ee",
            "pill_bg": "#f8fafc",
        }

    def _css_bytes(self) -> bytes:
        accent = self.config.accent
        p = self._palette()
        return (
            f"""
            window {{
                background: {p['bg']};
                color: {p['text']};
                border: 1px solid {p['border']};
                border-radius: 14px;
            }}
            label {{ color: {p['text']}; }}
            .card {{
                background: {p['card']};
                border-radius: 16px;
                border: 1px solid {p['border']};
                padding: 14px;
            }}
            .hero {{ padding: 18px 14px; }}
            .app-title {{ font-size: 14px; font-weight: 800; }}
            .section-title {{ font-weight: 800; font-size: 12px; }}
            .muted {{ color: {p['muted']}; font-size: 11px; }}
            .state-big {{ font-size: 19px; font-weight: 800; }}
            .badge {{
                border-radius: 999px;
                padding: 3px 12px;
                font-weight: 800;
                font-size: 11px;
            }}
            .badge.connected {{ background: #16331f; color: #4ade80; }}
            .badge.disconnected {{ background: #1d2942; color: #94a3b8; }}
            .badge.connecting {{ background: #3a2a12; color: #fbbf24; }}
            .badge.error {{ background: #3a1717; color: #f87171; }}
            .power-btn {{
                background: {accent};
                color: #ffffff;
                font-weight: 800;
                font-size: 14px;
                border-radius: 999px;
                padding: 12px 16px;
                border: none;
                box-shadow: none;
            }}
            .power-btn.on {{ background: {self.config.colors['connected']['primary']}; }}
            .power-btn:hover {{ opacity: 0.92; }}
            .power-btn:disabled {{ opacity: 0.6; }}
            .accent-btn {{
                background: {accent};
                color: #ffffff;
                font-weight: 800;
                border-radius: 10px;
                padding: 7px 14px;
                border: none;
                box-shadow: none;
            }}
            .accent-btn:hover {{ opacity: 0.92; }}
            .accent-btn:disabled {{ opacity: 0.5; }}
            .ghost-btn {{
                background: {p['ghost_bg']};
                color: {p['ghost_text']};
                font-weight: 700;
                border-radius: 10px;
                padding: 6px 12px;
                border: none;
            }}
            .ghost-btn:hover {{ background: {p['ghost_hover']}; }}
            entry {{
                border-radius: 9px;
                padding: 7px 9px;
                background: {p['entry_bg']};
                color: {p['text']};
                border: 1px solid {p['border']};
            }}
            list {{ background: transparent; }}
            row {{ border-radius: 9px; }}
            .host-pill {{
                background: {p['pill_bg']};
                border: 1px solid {p['border']};
                border-radius: 9px;
            }}
            .toast {{ font-size: 11px; }}
            .toast.ok {{ color: {p['muted']}; }}
            .toast.err {{ color: #f87171; }}
            stackswitcher button {{
                font-weight: 700;
                font-size: 11px;
                padding: 5px 12px;
                color: {p['muted']};
            }}
            stackswitcher button:checked {{ color: {accent}; }}
            """
        ).encode("utf-8")

    def _install_css(self) -> None:
        # Un error de CSS nunca debe impedir que la ventana se abra.
        try:
            self.css_provider.load_from_data(self._css_bytes())
        except Exception as exc:  # noqa: BLE001
            print(f"[warp-control] aviso: no se pudo cargar el CSS: {exc}", file=sys.stderr)
        screen = Gdk.Screen.get_default()
        if screen:
            Gtk.StyleContext.add_provider_for_screen(
                screen, self.css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def _reload_css(self) -> None:
        try:
            self.css_provider.load_from_data(self._css_bytes())
        except Exception as exc:  # noqa: BLE001
            print(f"[warp-control] aviso: no se pudo recargar el CSS: {exc}", file=sys.stderr)

    # ---------------------------- ventana --------------------------------- #
    def _build_window(self) -> None:
        self.window = Gtk.Window(title=APP_NAME)
        self.window.set_default_size(300, -1)
        self.window.set_size_request(300, -1)
        self.window.set_resizable(False)
        self.window.set_border_width(10)
        # Apariencia de "popup" en una esquina, como Windscribe:
        self.window.set_decorated(False)
        self.window.set_skip_taskbar_hint(True)
        self.window.set_skip_pager_hint(True)
        self.window.set_keep_above(True)
        try:
            self.window.set_gravity(Gdk.Gravity.NORTH_EAST)
        except Exception:
            pass
        self.window.connect("delete-event", self._on_window_close)
        try:
            self.window.set_icon_from_file(str(icon_file("connecting")))
        except Exception:
            pass

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.window.add(outer)

        # --- Cabecera compacta (icono + nombre + cerrar) ---
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        outer.pack_start(top, False, False, 0)
        small_icon = Gtk.Image()
        try:
            small_icon.set_from_pixbuf(
                GdkPixbuf.Pixbuf.new_from_file_at_scale(str(icon_file("connecting")), 20, 20, True)
            )
        except Exception:
            small_icon.set_from_icon_name("network-vpn-symbolic", Gtk.IconSize.BUTTON)
        top.pack_start(small_icon, False, False, 0)
        app_title = Gtk.Label(label="WARP Control")
        app_title.get_style_context().add_class("app-title")
        top.pack_start(app_title, False, False, 0)

        close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.BUTTON)
        close_btn.set_tooltip_text("Ocultar")
        close_btn.get_style_context().add_class("ghost-btn")
        close_btn.connect("clicked", lambda *_: self.window.hide())
        top.pack_end(close_btn, False, False, 0)

        # --- Bloque central de conexión (estilo Windscribe) ---
        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        hero.get_style_context().add_class("card")
        hero.get_style_context().add_class("hero")
        outer.pack_start(hero, False, False, 0)

        self.header_icon = Gtk.Image()
        self.header_icon.set_halign(Gtk.Align.CENTER)
        self._set_header_icon("connecting")
        hero.pack_start(self.header_icon, False, False, 0)

        self.state_big = Gtk.Label(label="Comprobando…")
        self.state_big.set_halign(Gtk.Align.CENTER)
        self.state_big.get_style_context().add_class("state-big")
        hero.pack_start(self.state_big, False, False, 0)

        badge_holder = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        badge_holder.set_halign(Gtk.Align.CENTER)
        self.status_badge = Gtk.Label(label="…")
        self.status_badge.get_style_context().add_class("badge")
        badge_holder.pack_start(self.status_badge, False, False, 0)
        hero.pack_start(badge_holder, False, False, 0)

        self.power_button = Gtk.Button(label="Conectar")
        self.power_button.get_style_context().add_class("power-btn")
        self.power_button.connect("clicked", self._toggle_connection)
        hero.pack_start(self.power_button, False, False, 4)

        # --- Selector de pestañas ---
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        # Que el alto/ancho sea el de la pestaña visible, no el de la más grande.
        self.stack.set_hhomogeneous(False)
        self.stack.set_vhomogeneous(False)
        switcher = Gtk.StackSwitcher()
        switcher.set_halign(Gtk.Align.CENTER)
        switcher.set_stack(self.stack)
        outer.pack_start(switcher, False, False, 0)

        # Limita el alto del contenido de las pestañas; si una pestaña es más
        # larga (Apariencia), aparece scroll en vez de estirar la ventana.
        stack_scroller = Gtk.ScrolledWindow()
        stack_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        stack_scroller.set_propagate_natural_width(True)
        stack_scroller.set_propagate_natural_height(True)
        stack_scroller.set_max_content_height(300)
        stack_scroller.add(self.stack)
        outer.pack_start(stack_scroller, True, True, 0)

        self.stack.add_titled(self._build_exclusions_page(), "exclusions", "Exclusiones")
        self.stack.add_titled(self._build_appearance_page(), "appearance", "Apariencia")

        # --- Mensaje / toast ---
        self.message_label = Gtk.Label()
        self.message_label.set_xalign(0)
        self.message_label.set_line_wrap(True)
        self.message_label.set_max_width_chars(34)
        self.message_label.set_width_chars(0)
        self.message_label.get_style_context().add_class("toast")
        outer.pack_start(self.message_label, False, False, 0)

        # --- Pie ---
        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        outer.pack_start(bottom, False, False, 0)

        self.autostart_check = Gtk.CheckButton(label="Iniciar con la sesión")
        self.autostart_check.set_active(AUTOSTART_FILE.exists())
        self.autostart_check.connect("toggled", self._toggle_autostart)
        bottom.pack_start(self.autostart_check, True, True, 0)

        refresh = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        refresh.set_tooltip_text("Actualizar")
        refresh.get_style_context().add_class("ghost-btn")
        refresh.connect("clicked", lambda *_: self.refresh_all())
        bottom.pack_end(refresh, False, False, 0)

        hide = Gtk.Button(label="Ocultar")
        hide.get_style_context().add_class("ghost-btn")
        hide.connect("clicked", lambda *_: self.window.hide())
        bottom.pack_end(hide, False, False, 0)

        self.window.show_all()
        self.window.hide()

    def _build_exclusions_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page.get_style_context().add_class("card")

        subtitle = Gtk.Label(label="Sitios que NO usarán la VPN")
        subtitle.set_xalign(0)
        subtitle.get_style_context().add_class("section-title")
        page.pack_start(subtitle, False, False, 0)

        explanation = Gtk.Label(
            label=(
                "Pega una URL completa o escribe un dominio. Se excluye el dominio "
                "entero del túnel; una ruta como /pagina no puede excluirse por separado."
            )
        )
        explanation.set_xalign(0)
        explanation.set_line_wrap(True)
        explanation.set_max_width_chars(34)
        explanation.set_width_chars(0)
        explanation.get_style_context().add_class("muted")
        page.pack_start(explanation, False, False, 0)

        entry_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        page.pack_start(entry_row, False, False, 0)

        self.host_entry = Gtk.Entry()
        self.host_entry.set_placeholder_text("https://ejemplo.com/ruta")
        self.host_entry.connect("activate", self._add_host)
        entry_row.pack_start(self.host_entry, True, True, 0)

        self.add_button = Gtk.Button(label="Añadir")
        self.add_button.get_style_context().add_class("accent-btn")
        self.add_button.connect("clicked", self._add_host)
        entry_row.pack_start(self.add_button, False, False, 0)

        self.subdomains_check = Gtk.CheckButton(
            label="Incluir también todos los subdominios (*.dominio.com)"
        )
        page.pack_start(self.subdomains_check, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(150)
        scroller.set_max_content_height(220)
        page.pack_start(scroller, True, True, 0)

        self.host_list = Gtk.ListBox()
        self.host_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroller.add(self.host_list)

        return page

    def _build_appearance_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page.get_style_context().add_class("card")

        # --- Modo oscuro ---
        theme_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        page.pack_start(theme_row, False, False, 0)
        theme_label = Gtk.Label(label="Modo oscuro")
        theme_label.set_xalign(0)
        theme_row.pack_start(theme_label, True, True, 0)
        self.theme_switch = Gtk.Switch()
        self.theme_switch.set_valign(Gtk.Align.CENTER)
        self.theme_switch.set_active(self.config.theme == "dark")
        self.theme_switch.connect("notify::active", self._on_theme_toggle)
        theme_row.pack_start(self.theme_switch, False, False, 0)

        page.pack_start(Gtk.Separator(), False, False, 0)

        title = Gtk.Label(label="Colores del icono")
        title.set_xalign(0)
        title.get_style_context().add_class("section-title")
        page.pack_start(title, False, False, 0)

        hint = Gtk.Label(
            label="Personaliza el color del icono de la bandeja para cada estado."
        )
        hint.set_xalign(0)
        hint.set_line_wrap(True)
        hint.set_max_width_chars(34)
        hint.set_width_chars(0)
        hint.get_style_context().add_class("muted")
        page.pack_start(hint, False, False, 0)

        grid = Gtk.Grid()
        grid.set_row_spacing(6)
        grid.set_column_spacing(8)
        page.pack_start(grid, False, False, 0)

        head = Gtk.Label(label="Estado"); head.set_xalign(0)
        head.get_style_context().add_class("muted")
        grid.attach(head, 0, 0, 1, 1)
        h1 = Gtk.Label(label="Principal"); h1.get_style_context().add_class("muted")
        grid.attach(h1, 1, 0, 1, 1)
        h2 = Gtk.Label(label="Secundario"); h2.get_style_context().add_class("muted")
        grid.attach(h2, 2, 0, 1, 1)

        for index, state in enumerate(("connected", "connecting", "disconnected", "error"), start=1):
            name = Gtk.Label(label=STATE_NAMES_ES[state])
            name.set_xalign(0)
            grid.attach(name, 0, index, 1, 1)
            self.color_buttons[state] = {}
            for col, key in enumerate(("primary", "secondary"), start=1):
                button = Gtk.ColorButton()
                button.set_rgba(hex_to_rgba(self.config.colors[state][key]))
                button.connect("color-set", self._on_color_set, state, key)
                grid.attach(button, col, index, 1, 1)
                self.color_buttons[state][key] = button

        accent_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        page.pack_start(accent_row, False, False, 0)
        accent_label = Gtk.Label(label="Color de acento de la app")
        accent_label.set_xalign(0)
        accent_row.pack_start(accent_label, True, True, 0)
        self.accent_button = Gtk.ColorButton()
        self.accent_button.set_rgba(hex_to_rgba(self.config.accent))
        self.accent_button.connect("color-set", self._on_accent_set)
        accent_row.pack_start(self.accent_button, False, False, 0)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.set_margin_top(6)
        page.pack_start(actions, False, False, 0)
        reset = Gtk.Button(label="Restablecer colores")
        reset.get_style_context().add_class("ghost-btn")
        reset.connect("clicked", self._on_reset_colors)
        actions.pack_end(reset, False, False, 0)

        return page

    def _set_header_icon(self, state: str) -> None:
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(icon_file(state)), 56, 56, True)
            self.header_icon.set_from_pixbuf(pixbuf)
        except Exception:
            self.header_icon.set_from_icon_name("network-vpn-symbolic", Gtk.IconSize.DIALOG)

    def _on_theme_toggle(self, switch: Gtk.Switch, _param) -> None:
        self.config.theme = "dark" if switch.get_active() else "light"
        self.config.save()
        self._reload_css()
        self._show_message("Modo oscuro activado." if switch.get_active() else "Modo claro activado.")

    # ---------------------------- indicador ------------------------------- #
    def _build_indicator(self) -> None:
        self.indicator = None
        if AppIndicator is None:
            self._show_message(
                "No se pudo cargar AppIndicator. La app funcionará como ventana, "
                "pero quizá no aparezca en la barra hasta reiniciar la sesión.",
                error=True,
            )
            return

        self.indicator = AppIndicator.Indicator.new(
            APP_ID, ICONS["connecting"], AppIndicator.IndicatorCategory.APPLICATION_STATUS
        )
        self.indicator.set_icon_theme_path(str(ICON_DIR))
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_title(APP_NAME)

        menu = Gtk.Menu()
        self.menu_status = Gtk.MenuItem(label="Estado: comprobando…")
        self.menu_status.set_sensitive(False)
        menu.append(self.menu_status)
        menu.append(Gtk.SeparatorMenuItem())

        open_item = Gtk.MenuItem(label="Abrir panel")
        open_item.connect("activate", lambda *_: self.show_window())
        menu.append(open_item)

        self.menu_toggle = Gtk.MenuItem(label="Conectar")
        self.menu_toggle.connect("activate", self._toggle_connection)
        menu.append(self.menu_toggle)

        refresh_item = Gtk.MenuItem(label="Actualizar")
        refresh_item.connect("activate", lambda *_: self.refresh_all())
        menu.append(refresh_item)
        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Salir")
        quit_item.connect("activate", lambda *_: Gtk.main_quit())
        menu.append(quit_item)

        menu.show_all()
        self.indicator.set_menu(menu)

    def _refresh_indicator_icon(self) -> None:
        """Fuerza al indicador a releer los SVG (tras cambiar de color)."""
        if self.indicator is None:
            return
        css = self.state if self.state in ICONS else "connecting"
        # Truco para que libappindicator note el cambio de archivo:
        self.indicator.set_icon_theme_path(str(ICON_DIR))
        self.indicator.set_icon_full(ICONS[css], STATE_LABELS.get(self.state, ""))

    # ---------------------------- hilos ----------------------------------- #
    @staticmethod
    def _background(function, callback) -> None:
        def worker() -> None:
            try:
                result = function()
            except Exception as exc:
                result = (False, str(exc))
            GLib.idle_add(callback, result)

        threading.Thread(target=worker, daemon=True).start()

    def _set_busy(self, value: bool) -> None:
        self.busy = value
        self.power_button.set_sensitive(not value)
        self.add_button.set_sensitive(not value)
        self.host_entry.set_sensitive(not value)
        if self.indicator is not None:
            self.menu_toggle.set_sensitive(not value)

    # ---------------------------- estado ---------------------------------- #
    def refresh_all(self) -> None:
        self.refresh_status()
        self.refresh_hosts()

    def _status_timer(self) -> bool:
        self.refresh_status()
        return True

    def refresh_status(self) -> None:
        if self.status_running or self.busy:
            return
        self.status_running = True
        self._background(lambda: run_warp("status"), self._status_finished)

    def _status_finished(self, result: tuple[bool, str]) -> bool:
        self.status_running = False
        ok, output = result
        if not ok:
            self._apply_status("error")
            self._show_message(output, error=True)
            return False
        self._apply_status(parse_status(output))
        return False

    def _apply_status(self, state: str) -> None:
        css_state = state if state in ICONS else "disconnected"
        text = STATE_LABELS.get(state, STATE_LABELS["unknown"])
        self.state = state

        context = self.status_badge.get_style_context()
        for class_name in ("connected", "disconnected", "connecting", "error"):
            context.remove_class(class_name)
        context.add_class(css_state)
        self.status_badge.set_text(text)
        self.state_big.set_text(text)
        self._set_header_icon(css_state)

        connected = state == "connected"
        self.power_button.set_label("Desconectar" if connected else "Conectar")
        power_context = self.power_button.get_style_context()
        if connected:
            power_context.add_class("on")
        else:
            power_context.remove_class("on")

        if self.indicator is not None:
            self.menu_status.set_label(f"Estado: {text}")
            self.menu_toggle.set_label("Desconectar" if connected else "Conectar")
            self.indicator.set_icon_full(ICONS[css_state], text)

    def _toggle_connection(self, *_args) -> None:
        if self.busy:
            return
        command = "disconnect" if self.state == "connected" else "connect"
        self._set_busy(True)
        self._apply_status("connecting")
        self._background(lambda: run_warp(command, timeout=50), self._connection_finished)

    def _connection_finished(self, result: tuple[bool, str]) -> bool:
        self._set_busy(False)
        ok, output = result
        if not ok:
            self._show_message(output, error=True)
        else:
            self._show_message("Estado de WARP actualizado.")
        GLib.timeout_add(700, self._refresh_once)
        return False

    def _refresh_once(self) -> bool:
        self.refresh_status()
        return False

    # ---------------------------- exclusiones ----------------------------- #
    def refresh_hosts(self) -> None:
        if self.hosts_running:
            return
        self.hosts_running = True
        self._background(lambda: run_warp("tunnel", "host", "list"), self._hosts_finished)

    def _hosts_finished(self, result: tuple[bool, str]) -> bool:
        self.hosts_running = False
        ok, output = result
        if not ok:
            self._show_message(output, error=True)
            return False
        self._render_hosts(parse_hosts(output))
        return False

    def _render_hosts(self, hosts: list[str]) -> None:
        for child in self.host_list.get_children():
            self.host_list.remove(child)

        if not hosts:
            empty = Gtk.Label(label="No hay dominios excluidos todavía.")
            empty.set_margin_top(18)
            empty.set_margin_bottom(18)
            empty.get_style_context().add_class("muted")
            self.host_list.add(empty)
        else:
            for host in hosts:
                row = Gtk.ListBoxRow()
                box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                box.set_border_width(8)
                box.get_style_context().add_class("host-pill")
                row.add(box)

                dot = Gtk.Image.new_from_icon_name("network-vpn-symbolic", Gtk.IconSize.BUTTON)
                box.pack_start(dot, False, False, 0)

                label = Gtk.Label(label=host)
                label.set_xalign(0)
                label.set_selectable(True)
                box.pack_start(label, True, True, 0)

                remove = Gtk.Button.new_from_icon_name("edit-delete-symbolic", Gtk.IconSize.BUTTON)
                remove.set_tooltip_text(f"Eliminar {host}")
                remove.get_style_context().add_class("ghost-btn")
                remove.connect("clicked", self._remove_host, host)
                box.pack_end(remove, False, False, 0)
                self.host_list.add(row)

        self.host_list.show_all()

    def _add_host(self, *_args) -> None:
        if self.busy:
            return
        try:
            host = normalize_host(self.host_entry.get_text())
        except ValueError as exc:
            self._show_message(str(exc), error=True)
            return

        hosts = [host]
        if self.subdomains_check.get_active() and not host.startswith("*.") and ":" not in host:
            hosts.append(f"*.{host}")

        self._set_busy(True)
        self._show_message("Añadiendo exclusión…")

        def operation() -> tuple[bool, str]:
            for item in hosts:
                ok, output = run_warp("tunnel", "host", "add", item)
                if not ok:
                    return False, output
            return True, ""

        self._background(operation, self._host_change_finished)

    def _remove_host(self, _button: Gtk.Button, host: str) -> None:
        if self.busy:
            return
        self._set_busy(True)
        self._show_message(f"Eliminando {host}…")

        def operation() -> tuple[bool, str]:
            ok, output = run_warp("tunnel", "host", "remove", host)
            if ok:
                return True, output
            help_ok, help_output = run_warp("tunnel", "host", "--help")
            if help_ok and "delete" in help_output.lower():
                return run_warp("tunnel", "host", "delete", host)
            return False, output

        self._background(operation, self._host_change_finished)

    def _host_change_finished(self, result: tuple[bool, str]) -> bool:
        self._set_busy(False)
        ok, output = result
        if not ok:
            self._show_message(output, error=True)
            return False
        self.host_entry.set_text("")
        self._show_message("Lista de exclusiones actualizada.")
        self.refresh_hosts()
        return False

    # ---------------------------- apariencia ------------------------------ #
    def _on_color_set(self, button: Gtk.ColorButton, state: str, key: str) -> None:
        self.config.colors[state][key] = rgba_to_hex(button.get_rgba())
        self.config.save()
        self.config.write_icons()
        self._reload_css()  # el botón de conexión usa el color "connected"
        self._set_header_icon(self.state if self.state in ICONS else "connecting")
        self._refresh_indicator_icon()
        self._show_message("Colores actualizados.")

    def _on_accent_set(self, button: Gtk.ColorButton) -> None:
        self.config.accent = rgba_to_hex(button.get_rgba())
        self.config.save()
        self._reload_css()
        self._show_message("Color de acento actualizado.")

    def _on_reset_colors(self, *_args) -> None:
        self.config.reset()
        self.config.save()
        self.config.write_icons()
        for state, keys in self.color_buttons.items():
            for key, button in keys.items():
                button.set_rgba(hex_to_rgba(self.config.colors[state][key]))
        self.accent_button.set_rgba(hex_to_rgba(self.config.accent))
        self._reload_css()
        self._set_header_icon(self.state if self.state in ICONS else "connecting")
        self._refresh_indicator_icon()
        self._show_message("Se restablecieron los colores por defecto.")

    # ---------------------------- ventana / varios ------------------------ #
    def show_window(self) -> None:
        self.window.show_all()
        self.window.present()
        self._position_corner()
        # Reposiciona cuando ya se conoce el tamaño real de la ventana.
        GLib.idle_add(self._position_corner)
        self.refresh_all()

    def _position_corner(self) -> bool:
        """Coloca la ventana en la esquina superior derecha (cerca de la bandeja).

        En X11 funciona directamente; en Wayland el compositor decide la
        posición y este movimiento se ignora de forma segura.
        """
        try:
            display = Gdk.Display.get_default()
            if display is None:
                return False
            monitor = None
            gdk_win = self.window.get_window()
            if gdk_win is not None and hasattr(display, "get_monitor_at_window"):
                monitor = display.get_monitor_at_window(gdk_win)
            if monitor is None and hasattr(display, "get_primary_monitor"):
                monitor = display.get_primary_monitor()
            if monitor is None and hasattr(display, "get_monitor"):
                monitor = display.get_monitor(0)
            if monitor is None:
                return False
            area = monitor.get_workarea()
            width, height = self.window.get_size()
            margin = 14
            x = area.x + area.width - width - margin
            y = area.y + margin
            self.window.move(x, y)
        except Exception:
            pass
        return False

    def _on_window_close(self, *_args) -> bool:
        if self.indicator is None:
            Gtk.main_quit()
        else:
            self.window.hide()
        return True

    def _show_message(self, text: str, error: bool = False) -> None:
        context = self.message_label.get_style_context()
        context.remove_class("ok")
        context.remove_class("err")
        context.add_class("err" if error else "ok")
        self.message_label.set_text(text or "")

    def _toggle_autostart(self, checkbox: Gtk.CheckButton) -> None:
        try:
            if checkbox.get_active():
                AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
                launcher = Path.home() / ".local" / "bin" / "warp-control"
                AUTOSTART_FILE.write_text(
                    "\n".join(
                        [
                            "[Desktop Entry]",
                            "Type=Application",
                            f"Name={APP_NAME}",
                            f"Exec={launcher} --background",
                            f"Icon={icon_file('connecting')}",
                            "Terminal=false",
                            "X-GNOME-Autostart-enabled=true",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )
                self._show_message("Inicio automático activado.")
            else:
                AUTOSTART_FILE.unlink(missing_ok=True)
                self._show_message("Inicio automático desactivado.")
        except OSError as exc:
            self._show_message(f"No se pudo cambiar el inicio automático: {exc}", error=True)


def main() -> int:
    # Nombre de clase estable para la ventana: KDE/KWin y la bandeja lo usan
    # para identificar la app (p. ej. para reglas de ventana que la anclen).
    try:
        GLib.set_prgname("warp-control")
    except Exception:
        pass
    try:
        controller = WarpControl()
    except Exception:  # noqa: BLE001
        import traceback

        details = traceback.format_exc()
        print(details, file=sys.stderr)
        try:
            dialog = Gtk.MessageDialog(
                transient_for=None,
                modal=True,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.CLOSE,
                text="WARP Control no pudo iniciarse",
            )
            dialog.format_secondary_text(details.strip().splitlines()[-1])
            dialog.run()
            dialog.destroy()
        except Exception:
            pass
        return 1
    if "--background" not in sys.argv:
        controller.show_window()
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

__WARP_CONTROL_PYTHON__
chmod 0755 "$APP_SCRIPT"

# Genera los iconos iniciales ejecutando el propio módulo (respeta la config
# guardada si ya existía; si no, usa los colores por defecto).
/usr/bin/python3 - "$ICON_DIR" "$CONFIG_DIR" <<'__GEN_ICONS__'
import json, re, sys
from pathlib import Path

icon_dir = Path(sys.argv[1])
config_file = Path(sys.argv[2]) / "config.json"
icon_dir.mkdir(parents=True, exist_ok=True)

TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="128" height="128">'
    '<path d="M16.493 17.4c.135-.52.08-.983-.161-1.338-.215-.328-.592-.519-1.05-.519'
    'l-8.663-.109a.148.148 0 01-.135-.082c-.027-.054-.027-.109-.027-.163.027-.082.108-.164'
    '.189-.164l8.744-.11c1.05-.054 2.153-.9 2.556-1.937l.511-1.31c.027-.055.027-.11.027-.164'
    'C17.92 8.91 15.66 7 12.942 7c-2.503 0-4.628 1.638-5.381 3.903a2.432 2.432 0 00-1.803-.491'
    'c-1.21.109-2.153 1.092-2.287 2.32-.027.328 0 .628.054.9C1.56 13.688 0 15.326 0 17.319'
    'c0 .19.027.355.027.545 0 .082.08.137.161.137h15.983c.08 0 .188-.055.215-.164l.107-.437" '
    'fill="{primary}"/>'
    '<path d="M19.238 11.75h-.242c-.054 0-.108.054-.135.109l-.35 1.2c-.134.52-.08.983.162 1.338'
    '.215.328.592.518 1.05.518l1.855.11c.054 0 .108.027.135.082.027.054.027.109.027.163-.027.082'
    '-.108.164-.188.164l-1.91.11c-1.05.054-2.153.9-2.557 1.937l-.134.355c-.027.055.026.137.107.137'
    'h6.592c.081 0 .162-.055.162-.137.107-.41.188-.846.188-1.31-.027-2.62-2.153-4.777-4.762-4.777" '
    'fill="{secondary}"/>'
    '</svg>'
)
DEFAULTS = {
    "connected": {"primary": "#16A34A", "secondary": "#4ADE80"},
    "connecting": {"primary": "#F38020", "secondary": "#FCAD32"},
    "disconnected": {"primary": "#64748B", "secondary": "#94A3B8"},
    "error": {"primary": "#DC2626", "secondary": "#F87171"},
}
NAMES = {
    "connected": "warp-control-connected",
    "connecting": "warp-control-connecting",
    "disconnected": "warp-control-disconnected",
    "error": "warp-control-error",
}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

colors = {k: dict(v) for k, v in DEFAULTS.items()}
try:
    data = json.loads(config_file.read_text(encoding="utf-8"))
    for state in DEFAULTS:
        entry = data.get("colors", {}).get(state, {})
        for key in ("primary", "secondary"):
            v = entry.get(key)
            if isinstance(v, str) and HEX.match(v):
                colors[state][key] = v.upper()
except Exception:
    pass

for state, name in NAMES.items():
    svg = TEMPLATE.format(**colors[state])
    (icon_dir / f"{name}.svg").write_text(svg, encoding="utf-8")
__GEN_ICONS__
chmod 0644 "$ICON_DIR"/*.svg

cat > "$BIN_FILE" <<EOF
#!/usr/bin/env bash
exec /usr/bin/python3 "$APP_SCRIPT" "\$@"
EOF
chmod 0755 "$BIN_FILE"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME
Comment=Controlar Cloudflare WARP y las exclusiones del túnel
Exec=$BIN_FILE
Icon=$ICON_DIR/warp-control-connecting.svg
Terminal=false
Categories=Network;Utility;
StartupNotify=false
StartupWMClass=warp-control
Keywords=Cloudflare;WARP;VPN;1.1.1.1;
EOF

cat > "$AUTOSTART_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME
Comment=Control de Cloudflare WARP
Exec=$BIN_FILE --background
Icon=$ICON_DIR/warp-control-connecting.svg
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

command -v desktop-file-validate >/dev/null 2>&1 && desktop-file-validate "$DESKTOP_FILE" || true
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true

# Intenta activar el soporte de iconos en GNOME. Puede requerir cerrar y abrir sesión.
if command -v gnome-extensions >/dev/null 2>&1; then
    gnome-extensions enable appindicatorsupport@rgcjonas.gmail.com >/dev/null 2>&1 || true
fi

info "Comprobando la sintaxis de la aplicación…"
/usr/bin/python3 -m py_compile "$APP_SCRIPT"
ok "Aplicación instalada correctamente."

info "Conectando WARP…"
if ! warp_cmd connect >/dev/null 2>&1; then
    warn "No fue posible conectar automáticamente. Podrás hacerlo desde el panel."
fi

pkill -f "$APP_SCRIPT" 2>/dev/null || true
if [[ -n "${DISPLAY:-}" || -n "${WAYLAND_DISPLAY:-}" ]]; then
    nohup "$BIN_FILE" >"$LOG_FILE" 2>&1 &
    disown || true
    ok "WARP Control se ha iniciado."
else
    warn "No se detectó una sesión gráfica. Abre 'WARP Control' desde el menú al iniciar sesión."
fi

cat <<EOF

============================================================
 Instalación terminada
============================================================

Aplicación:        $BIN_FILE
Acceso del menú:   $DESKTOP_FILE
Inicio automático: activado
Configuración:     $CONFIG_DIR/config.json
Registro de errores: $LOG_FILE

Uso:
  warp-control

Funciones del panel:
  • Pestaña "Exclusiones": añade URLs/dominios que NO pasarán por la VPN.
  • Pestaña "Apariencia": cambia los colores del icono de la bandeja.
  • Interruptor superior: conecta o desconecta WARP al instante.

Desinstalar solo esta interfaz (conserva tu configuración):
  $(basename "$0") --uninstall

Si el icono no aparece en la barra de GNOME, cierra la sesión y vuelve a entrar.
Las exclusiones se aplican por dominio, no por una ruta concreta de una URL.
EOF
