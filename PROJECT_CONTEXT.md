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

## Estado de implementación (2026-07-16)

- Plan activo: `docs/superpowers/plans/2026-07-16-warp-control-multidistro-implementation.md`.
- Tasks 1 y 2 terminadas y aprobadas mediante revisión de especificación y calidad.
- Paquete Python creado con configuración esquema 2, migración y persistencia atómica.
- Normalización de dominios usa IDNA 2008/UTS 46, conserva wildcards y rechaza notación IP ambigua.
- `CommandRunner` ejecuta argv sin shell y devuelve resultados tipados para fallos normales.
- Verificación actual: 61 pruebas aprobadas y Ruff limpio.
- Siguiente tarea: Task 3, servicio `WarpService` y detección de capacidades.
