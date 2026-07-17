# WARP Control Multidistro Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convertir WARP Control en una aplicación Python/GTK modular con la interfaz aprobada, instalación segura de Cloudflare WARP y paquetes nativos RPM, DEB y PKGBUILD.

**Architecture:** Un paquete Python bajo `src/` separará modelos, comandos, servicio WARP, instalación y UI. Una ventana GTK única alternará panel compacto y configuración; un StatusNotifierItem D-Bus abrirá el panel y AyatanaAppIndicator será el respaldo. Los paquetes nunca añadirán repositorios externos durante sus scriptlets: la instalación de WARP será una acción explícita autenticada por PolicyKit.

**Tech Stack:** Python 3.9+, PyGObject/GTK 3, Gio.DBus, pytest, Ruff, Bash, PolicyKit, RPM, Debian packaging, PKGBUILD, GitHub Actions.

---

## Mapa de archivos

- `pyproject.toml`: metadatos Python, entry point, Ruff y pytest.
- `src/warp_control/config.py`: esquema, persistencia, temas y colores.
- `src/warp_control/domains.py`: normalización de hosts.
- `src/warp_control/commands.py`: ejecución segura y resultados tipados.
- `src/warp_control/controller.py`: estado y orquestación sin dependencias GTK.
- `src/warp_control/services/warp.py`: API de alto nivel para `warp-cli`.
- `src/warp_control/services/autostart.py`: archivo autostart del usuario.
- `src/warp_control/services/diagnostics.py`: servicio, conectividad y logs.
- `src/warp_control/services/tasks.py`: workers y scheduler del main loop inyectables.
- `src/warp_control/installers/`: detección y planes de instalación por distro.
- `src/warp_control/privileged/`: helpers de instalación y reinicio, ambos sin argumentos.
- `src/warp_control/status_notifier.py`: integración D-Bus con bandeja.
- `src/warp_control/app_indicator.py`: respaldo Ayatana sin widgets arbitrarios.
- `src/warp_control/ui/`: ventana, panel y tres pestañas.
- `data/`: iconos, desktop, AppStream y PolicyKit.
- `packaging/`: RPM, Debian y Arch.
- `scripts/`: bootstrap y migración heredada.
- `tests/`: pruebas puras, de servicios, UI e instaladores.

### Task 1: Crear el paquete Python y el contrato de configuración

**Files:**
- Create: `pyproject.toml`
- Create: `src/warp_control/__init__.py`
- Create: `src/warp_control/__main__.py`
- Create: `src/warp_control/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Escribir pruebas fallidas de valores predeterminados, guardado y migración**

```python
def test_defaults_use_approved_palette(tmp_path):
    config = Config.load(tmp_path / "config.json")
    assert config.theme == "dark"
    assert config.accent == "#F38020"
    assert config.colors["connected"] == {"primary": "#16A34A", "secondary": "#4ADE80"}

def test_v1_config_is_migrated_without_losing_colors(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"theme":"light","accent":"#445566","colors":{}}')
    config = Config.load(path)
    assert config.schema_version == 2
    assert config.theme == "light"
    assert config.accent == "#445566"
```

- [ ] **Step 2: Ejecutar `python -m pytest tests/test_config.py -q` y confirmar `ModuleNotFoundError`**
- [ ] **Step 3: Implementar `Config.load`, `save`, `reset` y validación `#RRGGBB` con escritura atómica**
- [ ] **Step 4: Añadir `warp-control = "warp_control.__main__:main"` y configuración Ruff/pytest en `pyproject.toml`**
- [ ] **Step 5: Ejecutar `python -m pytest tests/test_config.py -q` y confirmar PASS**
- [ ] **Step 6: Commit `refactor: create warp control python package`**

### Task 2: Extraer dominios y ejecución segura de comandos

**Files:**
- Create: `src/warp_control/domains.py`
- Create: `src/warp_control/commands.py`
- Test: `tests/test_domains.py`
- Test: `tests/test_commands.py`

- [ ] **Step 1: Escribir casos de URL, wildcard, IDNA, ruta no separable y entrada inválida**

```python
@pytest.mark.parametrize(("value", "expected"), [
    ("https://Example.com/path", "example.com"),
    ("*.crm.example.com", "crm.example.com"),
    ("https://münich.example", "xn--mnich-kva.example"),
])
def test_normalize_host(value, expected):
    assert normalize_host(value) == expected
```

- [ ] **Step 2: Verificar que las pruebas fallan antes de implementar**
- [ ] **Step 3: Implementar `normalize_host`, `expand_host_rule` y `parse_hosts` sin GTK**
- [ ] **Step 4: Implementar `CommandResult(ok, stdout, stderr, returncode)` y `CommandRunner.run(argv, timeout)` con `shell=False`**
- [ ] **Step 5: Probar timeout, binario ausente y preservación separada de stdout/stderr**
- [ ] **Step 6: Ejecutar ambas suites y commit `refactor: extract domain and command services`**

### Task 3: Crear el servicio WARP y detección de capacidades

**Files:**
- Create: `src/warp_control/models.py`
- Create: `src/warp_control/services/warp.py`
- Test: `tests/services/test_warp.py`

- [ ] **Step 1: Escribir un `FakeRunner` y pruebas de parseo para connected, connecting, disconnected y error**
- [ ] **Step 1a: Probar explícitamente que `Disconnected` se evalúa antes que la subcadena `Connected`**
- [ ] **Step 2: Probar fallback cuando `--accept-tos` no es reconocido**
- [ ] **Step 3: Implementar `WarpService.status/connect/disconnect/list_hosts/add_host/remove_host`**
- [ ] **Step 4: Implementar `capabilities()` leyendo `warp-cli mode --help` y `warp-cli tunnel protocol --help`**
- [ ] **Step 5: Implementar cambios de modo/protocolo con retorno al valor anterior cuando falle el comando**
- [ ] **Step 6: Ejecutar `python -m pytest tests/services/test_warp.py -q` y commit `feat: add testable warp service`**

### Task 4: Implementar configuración de usuario, autostart e iconos

**Files:**
- Create: `src/warp_control/icons.py`
- Create: `src/warp_control/services/autostart.py`
- Create: `data/com.robler.warpcontrol.desktop`
- Create: `data/icons/cloudflare-template.svg`
- Test: `tests/test_icons.py`
- Test: `tests/services/test_autostart.py`

- [ ] **Step 1: Probar que el SVG usa Principal/Secundario de cada estado y no el acento**
- [ ] **Step 2: Probar enable/disable idempotente del autostart bajo un HOME temporal**
- [ ] **Step 3: Implementar renderizado de SVG con reemplazos validados y escritura atómica**
- [ ] **Step 4: Implementar autostart con `Exec=/usr/bin/warp-control --background` y activación predeterminada en primer arranque**
- [ ] **Step 5: Validar `desktop-file-validate data/com.robler.warpcontrol.desktop`**
- [ ] **Step 6: Commit `feat: add dynamic icons and autostart service`**

### Task 5: Construir la ventana única y las seis vistas aprobadas

**Files:**
- Create: `src/warp_control/ui/theme.py`
- Create: `src/warp_control/ui/compact_panel.py`
- Create: `src/warp_control/ui/exclusions.py`
- Create: `src/warp_control/ui/appearance.py`
- Create: `src/warp_control/ui/settings.py`
- Create: `src/warp_control/ui/main_window.py`
- Create: `src/warp_control/controller.py`
- Test: `tests/ui/test_theme.py`
- Test: `tests/ui/test_presenter.py`

- [ ] **Step 1: Probar que las paletas clara/oscura restauran la cabecera y que `accent` sustituye todo naranja fijo**
- [ ] **Step 2: Crear un presenter puro y probar etiquetas/botones para cada `WarpState`**
- [ ] **Step 3: Construir panel compacto con icono, estado, Conectar/Desconectar y Modificar**
- [ ] **Step 4: Construir una vista de configuración fija con tabs Exclusiones, Apariencia y Ajustes dentro del mismo `Gtk.Stack`**
- [ ] **Step 5: Conectar papelera SVG, colores, modo, autostart, actualización automática, modos, protocolos y herramientas**
- [ ] **Step 6: Asegurar viewport idéntico para las tres tabs y scroll interno; eliminar botones de recarga manual del diseño**
- [ ] **Step 7: Ejecutar pruebas puras y smoke test con `xvfb-run -a python -m warp_control --smoke-test`**
- [ ] **Step 8: Commit `feat: build unified light and dark gtk interface`**

### Task 6: Sustituir el menú de bandeja por StatusNotifierItem

**Files:**
- Create: `src/warp_control/status_notifier.py`
- Create: `src/warp_control/app_indicator.py`
- Create: `src/warp_control/tray.py`
- Test: `tests/test_status_notifier.py`

- [ ] **Step 1: Probar el adaptador D-Bus con un bus falso: Activate abre panel, ContextMenu usa fallback e icono cambia**
- [ ] **Step 2: Implementar las propiedades mínimas de `org.kde.StatusNotifierItem` usando `Gio.DBus`**
- [ ] **Step 3: Registrar el item ante `org.kde.StatusNotifierWatcher` y emitir cambio de icono por estado**
- [ ] **Step 4: Añadir fallback AyatanaAppIndicator con «Abrir panel», «Actualizar» y «Salir» cuando no haya watcher; no exportar Gtk.Switch**
- [ ] **Step 5: Verificar manualmente GNOME/AppIndicator y KDE; documentar la degradación**
- [ ] **Step 6: Commit `feat: open compact panel from status notifier`**

### Task 7: Integrar aplicación, tareas de fondo y logs

**Files:**
- Create: `src/warp_control/app.py`
- Create: `src/warp_control/services/diagnostics.py`
- Create: `src/warp_control/services/tasks.py`
- Modify: `src/warp_control/__main__.py`
- Test: `tests/test_app_controller.py`
- Test: `tests/services/test_diagnostics.py`

- [ ] **Step 1: Probar que el controlador evita refresh simultáneo y respeta el switch automático**
- [ ] **Step 2: Implementar workers daemon con callbacks `GLib.idle_add`, sin bloquear GTK**
- [ ] **Step 3: Implementar actualización predeterminada cada cinco segundos y cancelación limpia**
- [ ] **Step 4: Implementar restart, connectivity check y apertura del log con resultados tipados**
- [ ] **Step 5: Configurar logs rotativos bajo `~/.local/state/warp-control/` sin datos sensibles**
- [ ] **Step 6: Ejecutar tests y commit `feat: integrate warp control application lifecycle`**

### Task 8: Detectar distribución y crear planes de instalación

**Files:**
- Create: `src/warp_control/installers/models.py`
- Create: `src/warp_control/installers/detector.py`
- Create: `src/warp_control/installers/fedora.py`
- Create: `src/warp_control/installers/debian.py`
- Create: `src/warp_control/installers/rhel.py`
- Create: `src/warp_control/installers/unsupported.py`
- Test: `tests/installers/test_detector.py`
- Test: `tests/installers/test_plans.py`

- [ ] **Step 1: Probar Fedora 43/44, Ubuntu LTS, Debian 12/13, RHEL 9/10, Arch experimental y versión desconocida**
- [ ] **Step 2: Definir `InstallPlan(supported, warning, actions)` con acciones enum cerradas**
- [ ] **Step 3: Implementar lectura estricta de `/etc/os-release` y arquitectura**
- [ ] **Step 4: Implementar planes oficiales sin ejecutarlos; Arch solo devuelve instrucciones**
- [ ] **Step 5: Probar que ninguna versión desconocida produce acciones privilegiadas**
- [ ] **Step 6: Commit `feat: add multidistro installation planning`**

### Task 9: Añadir helper PolicyKit e instalación gráfica

**Files:**
- Create: `src/warp_control/privileged/helper.py`
- Create: `src/warp_control/privileged/runner.py`
- Create: `src/warp_control/privileged/repositories.py`
- Create: `src/warp_control/ui/install_dialog.py`
- Create: `data/com.robler.warpcontrol.policy`
- Create: `libexec/warp-control/install-warp`
- Create: `libexec/warp-control/restart-warp`
- Test: `tests/test_helper.py`
- Test: `tests/ui/test_install_presenter.py`

- [ ] **Step 1: Probar que ambos helpers rechazan cualquier argumento, stdin, EUID distinto de cero, distro no soportada, URL distinta y ejecución concurrente**
- [ ] **Step 2: Implementar dos entry points de propósito único: `install-warp` y `restart-warp`; ambos con entorno limpio, ejecutables absolutos y `shell=False`**
- [ ] **Step 3: Implementar Fedora/RHEL con repositorio oficial y Debian/Ubuntu con keyring `signed-by`**
- [ ] **Step 4: Construir diálogo Instalar ahora/Ver instrucciones/Ahora no con segunda confirmación**
- [ ] **Step 5: Invocar `pkexec /usr/libexec/warp-control/install-warp` sin argumentos y transmitir progreso JSONL validado**
- [ ] **Step 6: Añadir aceptación explícita antes de `registration new` y modo limitado tras cancelar**
- [ ] **Step 7: Ejecutar tests y commit `feat: add authorized cloudflare installation flow`**

### Task 10: Migrar el instalador heredado sin perder configuración

**Files:**
- Create: `scripts/install.sh`
- Create: `scripts/migrate-legacy.sh`
- Modify: `instalar-warp-control-fedora.sh`
- Test: `tests/shell/install.bats`
- Test: `tests/shell/migrate.bats`

- [ ] **Step 1: Probar detección de instalación heredada, dry-run, confirmación y preservación de config**
- [ ] **Step 2: Implementar migración que enumera y elimina solo rutas conocidas bajo `~/.local`**
- [ ] **Step 3: Convertir el script antiguo en wrapper de compatibilidad que delega a `scripts/install.sh`**
- [ ] **Step 4: Implementar bootstrap por paquete nativo; no embebir Python, iconos ni desktop files**
- [ ] **Step 5: Ejecutar Bats y `shellcheck scripts/*.sh instalar-warp-control-fedora.sh`**
- [ ] **Step 6: Commit `refactor: replace monolithic installer with package bootstrap`**

### Task 11: Crear el RPM de referencia

**Files:**
- Create: `packaging/rpm/warp-control.spec`
- Create: `data/com.robler.warpcontrol.metainfo.xml`
- Create: `MANIFEST.in`
- Create: `scripts/build-source-tarball.sh`
- Test: `tests/packaging/test_installed_layout.py`

- [ ] **Step 1: Probar que el wheel contiene data files y que el layout esperado usa `/usr/bin`, `/usr/share` y `/usr/libexec`**
- [ ] **Step 2: Escribir spec `BuildArch: noarch` con `%pyproject_buildrequires`, `%pyproject_wheel` y `%pyproject_install`; instalar assets y helpers explícitamente**
- [ ] **Step 3: Declarar solo dependencias Fedora disponibles; no `Requires: cloudflare-warp`**
- [ ] **Step 4: Construir dos veces el tarball reproducible, comparar SHA-256, construir SRPM/RPM y ejecutar `rpmlint`**
- [ ] **Step 5: Instalar en contenedor/VM Fedora, validar desktop/AppStream, lanzamiento y desinstalación**
- [ ] **Step 6: Commit `build: add native fedora rpm packaging`**

### Task 12: Crear DEB y PKGBUILD

**Files:**
- Create: `debian/control`
- Create: `debian/rules`
- Create: `debian/changelog`
- Create: `debian/copyright`
- Create: `debian/source/format`
- Create: `debian/warp-control.install`
- Create: `packaging/arch/PKGBUILD`
- Test: `tests/packaging/test_metadata.py`

- [ ] **Step 1: Probar que ningún metadata declara Cloudflare como dependencia oficial**
- [ ] **Step 2: Crear DEB `Architecture: all` con dependencias GTK/Python y helper PolicyKit**
- [ ] **Step 3: Construir con `dpkg-buildpackage -us -uc -b` y ejecutar `lintian`**
- [ ] **Step 4: Crear PKGBUILD para WARP Control sin dependencia AUR de Cloudflare y sin instalar helpers PolicyKit; documentar el soporte experimental**
- [ ] **Step 5: Construir con `makepkg --syncdeps --noconfirm` y ejecutar `namcap`**
- [ ] **Step 6: Commit `build: add debian and arch packaging`**

### Task 13: Añadir CI y documentación de portafolio

**Files:**
- Create: `.github/workflows/quality.yml`
- Create: `.github/workflows/packages.yml`
- Modify: `README.md`
- Create: `docs/ARCHITECTURE.md`
- Create: `docs/INSTALL.md`
- Create: `docs/SUPPORT.md`

- [ ] **Step 1: Añadir job Python para Ruff, pytest y smoke test GTK**
- [ ] **Step 2: Añadir jobs independientes para construir/validar RPM, DEB y PKGBUILD**
- [ ] **Step 3: Documentar matriz oficial/experimental con fecha y comandos de instalación**
- [ ] **Step 4: Añadir diagrama de módulos, trust boundary PolicyKit y capturas de seis pantallas**
- [ ] **Step 5: Ejecutar un linter de workflows y enlaces locales**
- [ ] **Step 6: Commit `ci: validate code and native linux packages`**

### Task 14: Verificación integral y entrega

**Files:**
- Modify: `PROJECT_CONTEXT.md`
- Modify: `NEXT_STEPS.md`
- Create: `CHANGELOG.md`

- [ ] **Step 1: Ejecutar `python -m ruff check .` y guardar salida limpia**
- [ ] **Step 2: Ejecutar `python -m pytest -q` y guardar total de pruebas aprobadas**
- [ ] **Step 3: Ejecutar validadores shell, desktop, AppStream y paquetes disponibles**
- [ ] **Step 4: Probar migración y primer arranque con `warp-cli` presente/ausente usando fakes**
- [ ] **Step 5: Revisar `git diff --check`, secretos y archivos generados**
- [ ] **Step 6: Actualizar contexto, changelog y commit `docs: complete multidistro warp control release`**

## Orden de ejecución con subagentes

1. Tasks 1-4 son secuenciales porque establecen contratos compartidos.
2. Tras Task 4, UI (Tasks 5-7) e instaladores (Tasks 8-9) pueden ejecutarse en paralelo con propietarios de archivos distintos.
3. Task 10 depende del formato de paquetes acordado, pero puede avanzar junto a Task 11 después de estabilizar el entry point.
4. Tasks 11 y 12 pueden ejecutarse en paralelo.
5. Tasks 13-14 integran todo y las ejecuta el agente principal.
