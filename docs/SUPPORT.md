# Compatibilidad

La aplicación se empaqueta para tres familias; la capacidad de instalar el
cliente WARP depende de la matriz oficial de Cloudflare vigente el 17 de julio
de 2026.

| Familia de WARP Control | Cliente Cloudflare WARP | Estado |
| --- | --- | --- |
| Fedora 43/44 y RHEL 9/10 | Repositorio RPM oficial | Compatible mediante confirmación en primer inicio. |
| Ubuntu 22.04/24.04/26.04 y Debian 12/13 | Repositorio APT oficial | Compatible mediante confirmación en primer inicio. |
| Arch Linux y derivadas | Fuente comunitaria/AUR | Experimental; no se automatiza. |
| Otras distribuciones | Sin plan de paquete actual | No soportado por el bootstrap. |

La arquitectura del paquete es independiente de WARP Control (`noarch`/`all`),
pero la disponibilidad del cliente WARP puede variar por arquitectura y
versión. Comprueba siempre la documentación de Cloudflare antes de desplegarlo
en equipos administrados.

## Requisitos de escritorio

- Python 3.9 o posterior, GTK 3 y PyGObject.
- Una bandeja compatible con StatusNotifierItem/AppIndicator. En GNOME puede
  ser necesaria una extensión de AppIndicator.
- `warp-cli` y `warp-svc` para conectar; sin ellos la interfaz sigue siendo
  segura, pero no puede crear el túnel.

## Política de soporte

Los artefactos de este repositorio son una demostración técnica y no están
afiliados con Cloudflare. Reporta problemas con versión de distribución,
versión de `warp-cli`, entorno de escritorio y pasos reproducibles; no incluyas
credenciales, identificadores de organización ni registros sensibles.
