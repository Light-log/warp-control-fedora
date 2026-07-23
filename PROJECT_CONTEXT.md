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
- Tasks 1–13 terminadas y aprobadas mediante revisión de especificación y calidad.
- Paquete Python creado con configuración esquema 2, migración y persistencia atómica.
- Normalización de dominios usa IDNA 2008/UTS 46, conserva wildcards y rechaza notación IP ambigua.
- `CommandRunner` ejecuta argv sin shell y devuelve resultados tipados para fallos normales.
- `WarpService` detecta capacidades de versiones nuevas y heredadas, aplica cambios con rollback seguro y nunca construye shell.
- Iconos Cloudflare de dos colores y autostart XDG se generan de forma atómica con rutas validadas.
- La ventana GTK única incluye panel compacto y tabs Exclusiones/Apariencia/Ajustes; conserva modo/protocolo, limpia proveedores CSS y carga SVG empaquetados.
- StatusNotifierItem adquiere el nombre D-Bus antes de registrarse, abre panel/menú y degrada a AyatanaAppIndicator sin fugas.
- El controlador serializa mutaciones WARP, descarta snapshots obsoletos, hace rollback de configuración y evita procesos ocultos sin bandeja.
- Logs rotativos solo guardan metadatos; `--smoke-test` funciona sin pantalla, D-Bus ni `warp-cli`.
- La detección fail-closed cubre la matriz oficial Cloudflare 2026 para RPM/APT; Arch solo ofrece instrucciones.
- El helper PolicyKit fija el fingerprint Cloudflare, restringe origen de paquetes, acota procesos/JSONL y suspende polling durante el flujo inicial.
- El instalador heredado ahora es un wrapper de siete líneas; el bootstrap usa snapshots con SHA-256 y la migración crea backups recuperables.
- RPM, DEB y PKGBUILD revisados con metadatos nativos; Arch fija una fuente Git a
  commit completo y se declara experimental.
- README renovado, documentación de arquitectura/instalación/compatibilidad,
  changelog, seis capturas GTK reales y CI independiente de calidad/RPM/DEB/Arch.
- Verificación actual: 385 pruebas aprobadas, 1 omitida (sin pantalla), Ruff
  limpio, scripts/metadata validados y wheel con SVG empaquetados validado.
- Task 14 terminado: suite completa, Ruff, smoke test, Bash, metadatos de
  escritorio/AppStream y RPM efímero comprobados. El RPM se generó desde el
  tarball limpio de `main` y contiene launcher, assets, PolicyKit y helpers.
- Pendiente externo: publicar `main` y, si se desea, adjuntar los artefactos de
  release; no hay cambios locales sin confirmar previstos.
