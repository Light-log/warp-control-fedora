# WARP Control — Fedora

Interfaz gráfica ligera para **Cloudflare WARP** en Fedora: icono en la bandeja del
sistema con estado en vivo, conexión con un clic y exclusión de dominios.

Todo (app de Python + GTK, icono SVG y dependencias) viaja dentro de un único script
instalador ejecutable.

> **Nota:** este proyecto se construyó cuando Cloudflare no ofrecía una interfaz gráfica
> oficial en Linux (solo `warp-cli` por terminal). Cloudflare ha lanzado desde entonces el
> **Cloudflare One Client**, que ya cubre este caso de uso. Mantengo el repositorio como
> proyecto de portafolio: integración con `warp-cli`, GUI nativa en GTK, gestión de estado
> en vivo y empaquetado para Fedora.

## Características

- **Icono en la bandeja del sistema** con estado en vivo: conectado / conectando /
  desconectado / error.
- **Mini panel en la bandeja**: un clic muestra el estado con un punto de color y un
  **interruptor** para conectar o desconectar al instante, sin abrir ninguna ventana.
- **Exclusiones**: añade URLs o dominios que **no** pasarán por la VPN, con opción de
  incluir todos los subdominios (split tunneling desde la interfaz).
- **Apariencia**: personaliza el color del icono para cada estado y el color de acento.
  Los cambios se guardan en `~/.config/warp-control/config.json` y se aplican al instante.
- **Instalador todo-en-uno**: resuelve dependencias gráficas, instala Cloudflare WARP y
  configura el servicio `warp-svc`.

## Requisitos

- Fedora (probado en Fedora Workstation)
- Entorno de escritorio con soporte de bandeja del sistema (GNOME requiere la extensión
  AppIndicator; el instalador la incluye)

## Instalación

### Opción rápida (una línea)

```bash
curl -fsSL https://raw.githubusercontent.com/Light-log/warp-control-fedora/main/instalar-warp-control-fedora.sh -o warp-control.sh && bash warp-control.sh
```

> Descarga el script y lo ejecuta. Si prefieres revisarlo antes (recomendable con
> cualquier script de internet), abre `warp-control.sh` entre los dos comandos.

### Opción manual

```bash
git clone https://github.com/Light-log/warp-control-fedora.git
cd warp-control-fedora
chmod +x instalar-warp-control-fedora.sh
./instalar-warp-control-fedora.sh
```

Ejecútalo como usuario normal — pedirá `sudo` solo cuando sea necesario.

Después, abre **WARP Control** desde el menú de aplicaciones o ejecuta:

```bash
warp-control
```

## Uso desde la bandeja

Un clic en el icono de la bandeja despliega un **mini panel** con:

- Un **punto de color** con el estado actual (verde conectado · naranja conectando ·
  gris desconectado · rojo error).
- Un **interruptor** para conectar o desconectar al instante, sin abrir la ventana.
- Accesos a **Abrir panel** (exclusiones y apariencia) y **Actualizar**.

## Desinstalación

Elimina solo la interfaz y conserva tu configuración (Cloudflare WARP permanece instalado):

```bash
./instalar-warp-control-fedora.sh --uninstall
```

## Cómo funciona

| Componente | Detalle |
|---|---|
| Interfaz | Python 3 + GTK 3 (`Gtk.Stack` con pestañas, CSS propio) |
| Bandeja | AppIndicator con icono SVG embebido en el script |
| Backend | Envuelve `warp-cli` y consulta el estado del servicio `warp-svc` |
| Configuración | JSON en `~/.config/warp-control/config.json` |
| Instalación | `~/.local/lib/warp-control` + lanzador `.desktop` |

## Stack

Bash · Python 3 · GTK 3 · AppIndicator · Cloudflare `warp-cli` · Fedora/RPM

## Licencia

MIT
