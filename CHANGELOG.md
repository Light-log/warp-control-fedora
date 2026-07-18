# Changelog

Los cambios relevantes se documentan aquí. El formato sigue una adaptación de
[Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y las versiones usan
versionado semántico.

## [2.0.0] - 2026-07-17

### Added

- Paquete Python real con interfaz GTK, controlador y servicios separados.
- Ventana única con panel compacto y pestañas Exclusiones, Apariencia y Ajustes.
- Colores configurables para estado, acento e icono de bandeja.
- Configuración atómica, validación IDNA y control de concurrencia de WARP.
- Flujo de instalación explícitamente confirmado mediante PolicyKit para RPM/APT.
- Empaquetado RPM, Debian y PKGBUILD experimental para Arch.
- CI de calidad, artefactos y documentación de arquitectura/compatibilidad.

### Security

- Ejecución de subprocessos con argv tipado, sin shell.
- Validación de helpers privilegiados, origen de paquetes y clave Cloudflare.
- Sin dependencias ni scriptlets de paquetes que instalen WARP silenciosamente.
