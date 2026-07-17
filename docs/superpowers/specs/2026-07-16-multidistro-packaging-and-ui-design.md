# WARP Control: diseño de reestructuración, interfaz y empaquetado multidistribución

Fecha: 2026-07-16

## 1. Propósito

Convertir WARP Control de un instalador Bash monolítico que genera Python mediante un heredoc en un proyecto Linux presentable como portafolio profesional. El resultado tendrá código Python modular, pruebas, metadatos de escritorio y paquetes nativos para varias familias de distribuciones.

El proyecto seguirá siendo una interfaz para `warp-cli`; no reemplazará el cliente ni el servicio de Cloudflare.

## 2. Objetivos

- Extraer la aplicación a un paquete Python importable y comprobable.
- Sustituir el menú limitado de AppIndicator por un panel compacto que responda a la activación del icono.
- Ofrecer una ventana de configuración consistente en modo claro y oscuro.
- Producir paquetes RPM, DEB y PKGBUILD desde una sola base de código.
- Detectar la ausencia de Cloudflare WARP y ofrecer una instalación explícitamente autorizada.
- Mostrar una matriz de soporte honesta y comprobable.
- Mantener el script actual únicamente como atajo de instalación; ya no contendrá código de la aplicación.
- Añadir pruebas, lint, validación de paquetes y documentación de arquitectura.

## 3. Fuera de alcance

- Publicar o mantener un repositorio COPR.
- Publicar en Flathub o empaquetar como Flatpak.
- Reimplementar el túnel, el protocolo WARP o `warp-svc`.
- Instalar paquetes comunitarios de AUR silenciosamente.
- Prometer compatibilidad oficial con distribuciones que Cloudflare no soporta.
- Añadir un servicio systemd propio; `warp-svc` pertenece al paquete de Cloudflare.

## 4. Matriz de soporte

La compatibilidad se documentará con fecha y versión. Al 2026-07-16, Cloudflare declara soporte para Fedora 43/44, Ubuntu 22.04/24.04/26.04, Debian 12/13 y RHEL 9/10.

| Nivel | Distribuciones | Paquete de WARP Control | Tratamiento de Cloudflare WARP |
|---|---|---|---|
| Soportado | Fedora 43/44 | RPM `noarch` | Instalación oficial con DNF, previa confirmación |
| Soportado | Ubuntu 22.04/24.04/26.04 | DEB `all` | Instalación oficial con APT, previa confirmación |
| Soportado | Debian 12/13 | DEB `all` | Instalación oficial con APT, previa confirmación |
| Soportado | RHEL 9/10 | RPM `noarch` | EPEL y paquete oficial, previa confirmación |
| Experimental | Arch, Manjaro, EndeavourOS | PKGBUILD | Se detecta `warp-cli`; si falta, se muestran instrucciones y advertencia sobre AUR |
| Sin validar | Otras distribuciones | Instalación desde código | Funciona solo si las dependencias GTK y `warp-cli` ya están disponibles |

Las versiones no incluidas en la matriz no se instalarán automáticamente. La aplicación explicará que la combinación no está validada y ofrecerá abrir instrucciones.

## 5. Arquitectura del repositorio

```text
GUI-Cloudflare/
├── pyproject.toml
├── src/
│   └── warp_control/
│       ├── __init__.py
│       ├── __main__.py
│       ├── app.py
│       ├── config.py
│       ├── models.py
│       ├── commands.py
│       ├── status_notifier.py
│       ├── services/
│       │   ├── warp.py
│       │   ├── autostart.py
│       │   ├── diagnostics.py
│       │   └── installer.py
│       ├── installers/
│       │   ├── detector.py
│       │   ├── fedora.py
│       │   ├── debian.py
│       │   ├── rhel.py
│       │   └── unsupported.py
│       └── ui/
│           ├── main_window.py
│           ├── compact_panel.py
│           ├── exclusions.py
│           ├── appearance.py
│           ├── settings.py
│           └── install_dialog.py
├── data/
│   ├── icons/
│   ├── com.robler.warpcontrol.desktop
│   ├── com.robler.warpcontrol.metainfo.xml
│   └── com.robler.warpcontrol.policy
├── packaging/
│   ├── rpm/warp-control.spec
│   └── arch/PKGBUILD
├── debian/
│   ├── control
│   ├── rules
│   └── source/format
├── scripts/
│   ├── install.sh
│   └── migrate-legacy.sh
└── tests/
```

Cada módulo tendrá una responsabilidad definida. La UI dependerá de interfaces de servicio y no ejecutará comandos directamente. `commands.py` aceptará listas de argumentos, nunca comandos construidos como cadenas de shell.

## 6. Bandeja y panel compacto

Los menús exportados por AppIndicator no transportan de forma fiable widgets arbitrarios como `Gtk.Switch`. Para permitir que un clic abra el panel diseñado, la implementación principal será un StatusNotifierItem sobre D-Bus usando `Gio.DBus`:

- `Activate(x, y)` mostrará u ocultará la ventana compacta cerca del puntero.
- `ContextMenu(x, y)` ofrecerá un menú nativo mínimo como respaldo.
- El icono publicado cambiará según el estado de WARP.
- Si no existe un StatusNotifierWatcher, se usará AyatanaAppIndicator como compatibilidad degradada y su menú tendrá «Abrir panel».

La única `Gtk.Window` tendrá dos vistas internas:

1. Panel compacto: icono Cloudflare, estado, acción Conectar/Desconectar y botón Modificar.
2. Configuración: cabecera, estado y pestañas Exclusiones, Apariencia y Ajustes.

«Modificar» cambia la vista dentro de la misma ventana. La configuración tendrá un ancho fijo equivalente al diseño aprobado y un área de contenido de altura fija; cada pestaña desplazará su propio contenido sin redimensionar la ventana.

## 7. Estados, temas y colores

Los estados serán `connected`, `connecting`, `disconnected`, `error` y `unknown`.

- El SVG de Cloudflare usará los colores Principal y Secundario del estado activo.
- El icono del StatusNotifierItem usará exactamente esos mismos SVG generados.
- El color de acento de la aplicación controlará pestaña activa, botones de acción, interruptores y botón Modificar.
- El botón Conectar/Desconectar y el indicador de estado usarán el color principal del estado, no el acento.
- El valor predeterminado del acento será `#F38020`, pero no habrá naranjas codificados fuera de la configuración predeterminada.

Modo claro:

- Cabecera integrada con fondo claro; no habrá una franja negra independiente.
- Superficies, textos y bordes usarán la paleta clara.

Modo oscuro:

- Cabecera integrada con fondo azul oscuro.
- Superficies, textos y bordes usarán la paleta oscura.

Cambiar tema o colores actualizará inmediatamente ventana, icono de bandeja y archivos SVG.

## 8. Pestañas de configuración

### 8.1 Exclusiones

- Campo para URL o dominio.
- Opción para incluir subdominios.
- Lista desplazable de exclusiones.
- Botón SVG de papelera para cada entrada.
- Validación y normalización del host antes de invocar `warp-cli`.

### 8.2 Apariencia

- Selector de modo claro/oscuro.
- Colores Principal y Secundario para cada estado.
- Color de acento de la interfaz.
- Restablecimiento de valores predeterminados.
- Vista previa aplicada en vivo.

### 8.3 Ajustes

- «Iniciar con la sesión» será el primer ajuste y estará activado inicialmente.
- «Actualizar automáticamente» estará activado inicialmente, con intervalo de cinco segundos.
- Selector de modo: WARP + DoH, WARP + DoT, WARP con DNS UDP, solo DoH, solo DoT, solo tráfico y proxy local.
- Selector de protocolo: MASQUE o WireGuard cuando el modo lo permita.
- Herramientas: reiniciar `warp-svc`, probar conectividad y abrir registro.

Los selectores consultarán primero las capacidades de la versión instalada mediante `warp-cli ... --help`; las opciones no soportadas quedarán ocultas o deshabilitadas.

## 9. Instalación de Cloudflare WARP

Los paquetes de WARP Control no declararán `cloudflare-warp` como dependencia obligatoria porque proviene de repositorios externos. Tampoco añadirán repositorios desde scripts `%post`, `postinst` o PKGBUILD.

Al iniciar:

1. `installer.py` busca `warp-cli`.
2. Si existe, la aplicación continúa y comprueba el registro.
3. Si falta, aparece un diálogo con «Instalar ahora», «Ver instrucciones» y «Ahora no».
4. «Instalar ahora» resume los cambios y requiere una segunda confirmación.
5. PolicyKit autentica la acción privilegiada.
6. Helpers de propósito único instalados en `/usr/libexec/warp-control/` ejecutan instalación o reinicio sin aceptar argumentos.
7. La UI muestra las etapas, captura errores y permite reintentar.

El helper no aceptará comandos arbitrarios. Validará `/etc/os-release`, arquitectura, versión soportada y URLs oficiales antes de modificar el sistema.

### Fedora

- Instalar la definición oficial del repositorio de Cloudflare.
- Actualizar metadatos solo para el repositorio necesario.
- Instalar `cloudflare-warp` mediante DNF.
- Activar `warp-svc`.

### Ubuntu y Debian

- Instalar la clave oficial en `/usr/share/keyrings`.
- Crear una fuente APT con `signed-by` y el codename validado.
- Ejecutar `apt-get update` e instalar `cloudflare-warp`.
- Activar `warp-svc`.

### RHEL

- Instalar EPEL tras explicarlo y obtener confirmación.
- Añadir el repositorio oficial de Cloudflare.
- Instalar `cloudflare-warp` y activar el servicio.

### Arch y derivadas

Cloudflare no ofrece un paquete oficial. WARP Control no ejecutará automáticamente un helper AUR. El diálogo explicará el carácter experimental y abrirá instrucciones para instalar un paquete comunitario. Después comprobará de nuevo la presencia de `warp-cli`.

### Registro inicial

Después de instalar, la aplicación ejecutará `warp-cli registration show`. Si no existe registro, solicitará aceptación de los términos y ejecutará `warp-cli registration new`. La cancelación dejará la aplicación en modo limitado.

## 10. Empaquetado

### RPM

- Paquete Python `noarch` construido desde un tarball de fuente reproducible.
- Uso de macros `%pyproject_*` y rutas estándar.
- Dependencias limitadas a paquetes disponibles en la distribución.
- Inclusión explícita de `.desktop`, AppStream, iconos y PolicyKit.
- Validación con `rpmlint` y `desktop-file-validate`.

### DEB

- Paquete `Architecture: all` con `debian/control`, `rules`, `copyright` y changelog.
- Dependencias GTK/Python nativas de Debian y Ubuntu.
- Validación con `lintian` y `desktop-file-validate`.

### Arch

- PKGBUILD para WARP Control únicamente.
- La necesidad de `warp-cli` se documentará, pero no se declarará un paquete AUR como dependencia.
- El paquete experimental no instalará helpers PolicyKit; mostrará instrucciones y comprobará `warp-cli`.
- Validación con `namcap`.

## 11. Instalador opcional

`scripts/install.sh` detectará la familia de distribución, explicará qué hará y pedirá confirmación antes de cualquier cambio privilegiado. Instalará el paquete nativo de WARP Control y podrá ofrecer la instalación oficial de Cloudflare en las distribuciones soportadas.

No contendrá Python, iconos ni archivos `.desktop` embebidos. En Arch solo instalará WARP Control y mostrará las instrucciones experimentales de Cloudflare.

## 12. Configuración y migración

- Se conservará `~/.config/warp-control/config.json`.
- Se añadirá un número de versión de esquema y migraciones idempotentes.
- El lanzador del paquete usará `/usr/bin/warp-control` de forma absoluta.
- En el primer arranque se detectará la instalación heredada bajo `~/.local/lib/warp-control`.
- Se ofrecerá eliminar únicamente los ejecutables heredados después de mostrar la lista; la configuración no se borrará.
- `scripts/migrate-legacy.sh` proporcionará el mismo flujo de forma explícita.

## 13. Errores y modo limitado

La ausencia de WARP, permisos rechazados, servicio detenido o modo no soportado no cerrarán la aplicación.

- El panel mostrará un estado comprensible y una acción de recuperación.
- Los detalles técnicos se escribirán en el registro del usuario.
- Las acciones privilegiadas mostrarán exactamente qué falló, sin incluir secretos.
- La UI nunca bloqueará el hilo GTK mientras se ejecuta DNF, APT, systemctl o `warp-cli`.
- Los cambios de modo que fallen restaurarán la selección anterior.

## 14. Seguridad

- PolicyKit autorizará acciones concretas, no una shell general.
- Todas las llamadas usarán argumentos separados y rutas absolutas para herramientas privilegiadas.
- Los temporales se crearán con permisos privados y nombres aleatorios.
- Las fuentes de paquetes usarán HTTPS y claves oficiales.
- La instalación de repositorios externos requerirá consentimiento visible.
- La aplicación no almacenará contraseñas ni claves de PolicyKit.

## 15. Pruebas y CI

Pruebas unitarias:

- Parseo de estados y modos de `warp-cli`.
- Normalización de dominios y subdominios.
- Lectura, escritura y migración de configuración.
- Detección de distribución y selección del instalador.
- Construcción de comandos sin shell.
- Transiciones de estado, actualización automática y rollback de selectores.

Pruebas de UI con servicios simulados:

- Panel compacto para todos los estados.
- Seis combinaciones de pestaña y tema.
- Propagación de colores al icono y controles.
- Diálogo de instalación, cancelación y reintento.
- Tamaño estable al cambiar de pestaña.

Validación de proyecto:

- `ruff` y pruebas Python.
- `shellcheck` para scripts.
- Construcción y `rpmlint` en Fedora.
- Construcción y `lintian` en Ubuntu/Debian.
- Construcción y `namcap` en Arch.
- Smoke test GTK bajo un servidor gráfico virtual.

## 16. Entregables y fases

1. Extraer y probar el núcleo Python sin modificar comportamiento.
2. Implementar la ventana única, StatusNotifierItem y diseño aprobado.
3. Añadir Ajustes, modos, protocolos y herramientas.
4. Implementar detección e instalación autorizada de Cloudflare.
5. Crear RPM y migración desde el instalador heredado.
6. Crear DEB para Ubuntu/Debian.
7. Crear PKGBUILD y documentación experimental para Arch.
8. Añadir CI, capturas, arquitectura y documentación final.

El RPM será el artefacto de referencia del portafolio. DEB y PKGBUILD demostrarán que el núcleo no depende de una sola distribución, sin convertir COPR o AUR en servicios que haya que mantener.

## 17. Criterios de aceptación

- El repositorio no contiene código Python dentro de heredocs.
- La aplicación arranca desde código instalado por RPM, DEB y PKGBUILD.
- Fedora, Ubuntu, Debian y RHEL muestran un flujo autorizado de instalación de WARP cuando falta.
- Arch se identifica como experimental y no instala AUR silenciosamente.
- El clic primario del icono abre el panel compacto donde StatusNotifierItem esté disponible.
- Las tres pestañas mantienen el mismo tamaño en ambos temas.
- El botón de papelera es un icono SVG de papelera.
- El acento configura navegación y acciones; los colores de estado configuran el icono y el estado.
- La cabecera sigue correctamente el tema claro u oscuro.
- Las pruebas y validadores de los tres formatos terminan correctamente.
- La configuración existente se conserva durante la migración.
