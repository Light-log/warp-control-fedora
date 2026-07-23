# WARP Control Linux Release Coverage Design

**Fecha:** 2026-07-22

**Estado:** aprobado conceptualmente; pendiente de revisión del documento

**Objetivo:** entregar WARP Control como una aplicación instalable en las familias Linux principales y como AppImage portátil, preservando el sistema de archivos y el modelo de seguridad existentes.

## Alcance real

“Multiplataforma Linux” significa cobertura práctica por familias de distribución, no prometer compatibilidad con cualquier kernel, libc o cliente WARP comunitario.

| Nivel | Sistemas | Artefacto WARP Control | Cliente Cloudflare WARP |
| --- | --- | --- | --- |
| Oficial | Fedora 43/44, RHEL 9/10 | RPM `noarch` | Repositorio oficial, tras confirmación |
| Oficial | Debian 12/13, Ubuntu 22.04/24.04/26.04 | DEB `all` | Repositorio oficial, tras confirmación |
| Comunitario | Arch Linux y derivadas compatibles | Paquete de `makepkg` | Instalación manual, sin automatizar AUR |
| Portátil | Otras distribuciones de escritorio basadas en glibc | AppImage x86_64 y aarch64 | `warp-cli`/`warp-svc` ya instalados por el usuario |

La matriz oficial se basa en la documentación de Cloudflare consultada el 22 de julio de 2026. Alpine/musl, sistemas sin GTK 3 o sin un cliente WARP funcional quedan fuera del soporte garantizado. Windows y macOS no forman parte de este proyecto.

Fuente primaria: [requisitos y versiones estables de Cloudflare One Client](https://developers.cloudflare.com/cloudflare-one/team-and-resources/devices/cloudflare-one-client/download/). RHEL 9/10 requiere además EPEL según esa matriz.

## Principios

1. Los paquetes de WARP Control nunca instalarán Cloudflare WARP desde `%post`, `postinst`, PKGBUILD o AppImage.
2. Solo Fedora/RHEL y Debian/Ubuntu ofrecerán instalación asistida del cliente oficial, con explicación y PolicyKit.
3. Arch y AppImage mostrarán instrucciones; no ejecutarán gestores comunitarios ni helpers privilegiados de instalación.
4. Los artefactos de release serán reproducibles desde un tag y se publicarán con SHA-256.
5. La estructura actual se conserva. No se reescribe el paquete Python ni se mueve la configuración del usuario.

## Sistema de archivos

Los paquetes nativos mantienen el layout existente:

- `/usr/bin/warp-control`
- módulos Python bajo el directorio `site-packages` de la distribución
- `/usr/share/applications/com.robler.warpcontrol.desktop`
- `/usr/share/icons/hicolor/scalable/apps/com.robler.warpcontrol.svg`
- `/usr/share/metainfo/com.robler.warpcontrol.metainfo.xml`
- PolicyKit y helpers únicamente en RPM/DEB compatibles

Los datos del usuario permanecen en:

- `${XDG_CONFIG_HOME:-~/.config}/warp-control/config.json`
- `${XDG_CONFIG_HOME:-~/.config}/autostart/warp-control.desktop`
- rutas de iconos generados ya administradas por `IconService`

La instalación AppImage será local y reversible:

- `~/.local/opt/warp-control/WARP-Control-<versión>-<arquitectura>.AppImage`
- `~/.local/bin/warp-control` como enlace al AppImage activo
- `~/.local/share/applications/com.robler.warpcontrol.desktop`
- `~/.local/share/icons/hicolor/scalable/apps/com.robler.warpcontrol.svg`

Actualizar o eliminar el AppImage no borra la configuración ni modifica `warp-svc`.

## Componentes nuevos

### AppImage

Se añade `packaging/appimage/` con una receta declarativa y un lanzador que resuelve la ruta interna sin asumir `/usr/bin`. El artefacto incluye Python, GTK/PyGObject, `idna`, assets y la aplicación; no incluye `warp-cli`, `warp-svc`, PolicyKit ni gestores de paquetes.

Se construyen dos arquitecturas en runners nativos: `x86_64` y `aarch64`. Cada AppImage ejecuta `--smoke-test`, se inspecciona con `--appimage-extract`, y se prueba en una sesión X virtual.

### Instalador unificado

`scripts/install.sh` mantiene su comportamiento para paquetes locales y añade soporte explícito para `.AppImage`:

- Detecta RPM, DEB, paquete Arch o AppImage por formato, no solo por nombre.
- Para paquetes nativos conserva el snapshot privado, SHA-256, confirmación y gestor correspondiente.
- Para AppImage instala exclusivamente en el home del usuario, sin `sudo`.
- `--dry-run` muestra todas las rutas y acciones.
- Rechaza enlaces simbólicos, archivos con permisos inseguros y arquitecturas incompatibles.

No descargará automáticamente el “último release”. El usuario aporta un archivo o usa la página de GitHub Releases, evitando ejecutar contenido remoto no revisado.

### Releases y CI

La CI queda dividida en:

1. calidad y pruebas Python;
2. RPM en Fedora;
3. DEB en Ubuntu/Debian;
4. paquete Arch en contenedor Arch;
5. AppImage x86_64/aarch64;
6. ensamblado de release solo desde tags `v*`.

El job de release descarga los artefactos construidos por los jobs anteriores, genera `SHA256SUMS`, verifica que la versión del tag coincida con `pyproject.toml` y publica mediante GitHub Actions. Ningún job reutiliza un paquete generado en una rama distinta.

El PKGBUILD deja de fijar un commit histórico del desarrollo. Habrá un único PKGBUILD publicado: usa el tarball del tag y un SHA-256 real, actualizado por `scripts/update-release-metadata.sh`. En pull requests, CI crea una copia efímera que apunta al tarball determinista del checkout; esa sustitución nunca se confirma ni introduce `SKIP` en el archivo de release.

## Experiencia del usuario

El README conserva las seis capturas existentes y añade una tabla de descargas:

- Fedora/RHEL: descargar RPM e instalar con `dnf`.
- Debian/Ubuntu: descargar DEB e instalar con `apt`.
- Arch: descargar el paquete construido o revisar el PKGBUILD.
- Otras distribuciones glibc: descargar AppImage, dar permiso de ejecución e iniciar.

Al primer inicio se muestran tres resultados posibles:

- cliente WARP disponible: abrir normalmente;
- sistema con repositorio oficial: ofrecer instalación confirmada;
- sistema comunitario/portátil: explicar que debe instalar `warp-cli` por separado y permitir reintentar.

La clasificación reutiliza el detector fail-closed actual: IDs/versiones incluidos en la matriz RPM/APT son oficiales; `arch`, `manjaro` y sus `ID_LIKE` son comunitarios; cualquier otro sistema que ejecute el AppImage es portátil. Una versión desconocida de una familia oficial se trata como portátil, nunca como autorización para instalar un repositorio.

## Errores y seguridad

- Un fallo de construcción en cualquier plataforma bloquea la publicación completa.
- Un checksum ausente o distinto bloquea el release.
- El AppImage marca las funciones de túnel como no disponibles si no encuentra `warp-cli`, muestra instrucciones y permite reintentar; no intenta elevar privilegios.
- Los helpers continúan validando distribución, UID, comandos y huella de clave.
- La aplicación nunca presenta soporte “oficial” fuera de la matriz publicada por Cloudflare.

## Pruebas de aceptación

En este diseño, `--smoke-test` significa que el ejecutable instalado puede importar todos los módulos y assets empaquetados, cargar una configuración temporal, construir los servicios/controlador con adaptadores falsos y terminar con código 0 sin pantalla, D-Bus, `warp-cli` ni cambios en el sistema. Cualquier excepción, asset ausente o acceso real a esos servicios produce código distinto de 0.

1. RPM se construye e instala en Fedora y pasa `--smoke-test`.
2. DEB se construye e instala en Ubuntu y Debian y pasa `--smoke-test`.
3. El paquete Arch se construye con `makepkg`, instala solo WARP Control y pasa `--smoke-test` cuando existe `warp-cli` simulado.
4. Ambos AppImage se extraen, contienen assets, ejecutan `--smoke-test` y no contienen helpers PolicyKit ni WARP.
5. El instalador selecciona correctamente los cuatro formatos, valida arquitectura y no usa privilegios para AppImage.
6. La configuración esquema 2 y sus backups sobreviven a actualizaciones entre cualquier artefacto.
7. Un tag de prueba produce los cuatro tipos de artefacto y `SHA256SUMS` sin publicar si una matriz falla.
8. El README muestra las seis capturas, comandos de instalación y límites de soporte.

## Fuera de alcance

- Windows, macOS, Flatpak, Snap, NixOS nativo y Alpine/musl.
- Empaquetar o redistribuir el cliente propietario de Cloudflare.
- Instalar paquetes AUR automáticamente.
- COPR, PPA o repositorios propios antes de validar demanda real.
