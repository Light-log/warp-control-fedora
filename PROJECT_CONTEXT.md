# Contexto del proyecto

WARP Control es una interfaz GTK para `warp-cli`. El repositorio actual contiene un único instalador Bash que genera la aplicación Python. El diseño aprobado el 2026-07-16 reestructura el proyecto como paquete Python real, añade una ventana única con panel compacto y tres pestañas, y produce RPM, DEB y PKGBUILD.

La especificación vigente es `docs/superpowers/specs/2026-07-16-multidistro-packaging-and-ui-design.md`.

Decisiones principales:

- RPM como artefacto central de portafolio; sin COPR por ahora.
- DEB para Ubuntu/Debian y PKGBUILD experimental para Arch.
- Instalación de Cloudflare solo tras confirmación y PolicyKit; nunca desde `%post`.
- Arch no instala AUR automáticamente.
- Una sola ventana GTK con panel compacto y vista de configuración.
- Colores de estado para el icono; color de acento para acciones y navegación.
- Cabecera integrada con el tema y pestañas de tamaño fijo.

## Estado de implementación (2026-07-17)

- Plan activo: `docs/superpowers/plans/2026-07-16-warp-control-multidistro-implementation.md`.
- Tasks 1–7 terminadas y aprobadas mediante revisión de especificación y calidad.
- Paquete Python creado con configuración esquema 2, migración y persistencia atómica.
- Normalización de dominios usa IDNA 2008/UTS 46, conserva wildcards y rechaza notación IP ambigua.
- `CommandRunner` ejecuta argv sin shell y devuelve resultados tipados para fallos normales.
- `WarpService` detecta capacidades de versiones nuevas y heredadas, aplica cambios con rollback seguro y nunca construye shell.
- Iconos Cloudflare de dos colores y autostart XDG se generan de forma atómica con rutas validadas.
- La ventana GTK única incluye panel compacto y tabs Exclusiones/Apariencia/Ajustes; conserva modo/protocolo, limpia proveedores CSS y carga SVG empaquetados.
- StatusNotifierItem adquiere el nombre D-Bus antes de registrarse, abre panel/menú y degrada a AyatanaAppIndicator sin fugas.
- El controlador serializa mutaciones WARP, descarta snapshots obsoletos, hace rollback de configuración y evita procesos ocultos sin bandeja.
- Logs rotativos solo guardan metadatos; `--smoke-test` funciona sin pantalla, D-Bus ni `warp-cli`.
- Verificación actual: 196 pruebas aprobadas localmente (203 con display en revisión), Ruff limpio y wheel con SVG empaquetados validado.
- Siguiente tarea: Task 8, detección multidistro y planes de instalación.
