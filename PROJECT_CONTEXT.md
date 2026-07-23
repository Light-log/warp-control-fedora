# Contexto del proyecto

WARP Control es una interfaz GTK para `warp-cli`, organizada como un paquete
Python real bajo `src/warp_control`. Ofrece una ventana única con panel compacto
y pestañas de Exclusiones, Apariencia y Ajustes, además de integración con la
bandeja. La especificación funcional original está en
`docs/superpowers/specs/2026-07-16-multidistro-packaging-and-ui-design.md` y la
cobertura de releases Linux en
`docs/superpowers/specs/2026-07-22-linux-release-coverage-design.md`.

## Decisiones vigentes

- Solo Linux: no se publican artefactos para Windows ni macOS.
- WARP Control y Cloudflare WARP tienen matrices diferentes. El AppImage hace
  portátil el panel, pero no convierte una distribución en oficialmente
  soportada por Cloudflare.
- La instalación de WARP requiere confirmación y PolicyKit; ningún scriptlet de
  paquete agrega repositorios de terceros.
- El PKGBUILD usa el tarball versionado y su SHA-256; Arch usa una fuente
  comunitaria para WARP y WARP Control no automatiza AUR.
- El ID de aplicación canónico es `com.devruby.warpcontrol`.
- Los artefactos de release se construyen desde una fuente reproducible y la
  publicación por etiqueta verifica nombres, versiones y SHA-256.

## Cobertura implementada

- La matriz RPM construye e instala de forma aislada en Fedora 43/44 y Rocky
  Linux 9/10: `warp-control-2.0.0-1.fc43.noarch.rpm`,
  `warp-control-2.0.0-1.fc44.noarch.rpm`,
  `warp-control-2.0.0-1.el9.noarch.rpm` y
  `warp-control-2.0.0-1.el10.noarch.rpm`.
- La matriz DEB construye e instala de forma aislada en Ubuntu
  22.04/24.04/26.04 y Debian 12/13, con sufijos `all-ubuntu2204.deb`, `all-ubuntu2404.deb`,
  `all-ubuntu2604.deb`, `all-debian12.deb` y `all-debian13.deb`.
- Arch: `warp-control-2.0.0-1-any.pkg.tar.zst`.
- AppImage nativo en ambas arquitecturas:
  `WARP-Control-2.0.0-x86_64.AppImage` y
  `WARP-Control-2.0.0-aarch64.AppImage`; incluye Python, GTK y PyGObject, pero
  mantiene `warp-cli` y `warp-svc` como componentes externos.
- Fuente: `warp-control-2.0.0.tar.gz`; manifiesto: `SHA256SUMS`.

## Estado local

Las tareas de fuente reproducible, rutas portátiles, construcción AppImage,
identidad de la aplicación, integración local sin privilegios, matrices de
paquetes y publicación por etiquetas están implementadas en `main`. Las seis
capturas GTK reales permanecen en `docs/screenshots`. Solo quedan operaciones
remotas, enumeradas en `NEXT_STEPS.md`.

La construcción e instalación se reprodujeron localmente en contenedores
limpios para Ubuntu 22.04 y Rocky Linux 9.8; las demás celdas están definidas y
se comprobarán en GitHub Actions después del push autorizado.
