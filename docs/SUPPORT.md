# Compatibilidad Linux

WARP Control se publica exclusivamente para Linux. No se producen ni se prueban
instaladores para Windows o macOS. La cobertura del panel y el soporte del
cliente Cloudflare WARP son dos cosas distintas.

| Familia de WARP Control | Cliente Cloudflare WARP | Estado |
| --- | --- | --- |
| Fedora 43/44 y RHEL 9/10 | Repositorio RPM oficial | Compatible mediante confirmación en primer inicio. |
| Ubuntu 22.04/24.04/26.04 y Debian 12/13 | Repositorio APT oficial | Compatible mediante confirmación en primer inicio. |
| Arch Linux y derivadas | Fuente comunitaria/AUR | Experimental; no se automatiza. |
| Otras distribuciones Linux (`x86_64`/`aarch64`) | AppImage de WARP Control | El panel es portátil; WARP se prepara por separado. |

El AppImage amplía la cobertura de WARP Control, pero no amplía el soporte
oficial de Cloudflare WARP. En una distribución fuera de la matriz de
Cloudflare, disponer del panel no garantiza que `warp-cli` o `warp-svc` estén
disponibles ni soportados.

La arquitectura del paquete es independiente de WARP Control (`noarch`/`all`),
pero la disponibilidad del cliente WARP puede variar por arquitectura y
versión. Comprueba siempre la documentación de Cloudflare antes de desplegarlo
en equipos administrados.

## Requisitos de escritorio

- Los paquetes nativos requieren Python 3.9 o posterior, GTK 3 y PyGObject; el
  AppImage ya incluye esos componentes.
- Una bandeja compatible con StatusNotifierItem/AppIndicator. En GNOME puede
  ser necesaria una extensión de AppIndicator.
- `warp-cli` y `warp-svc` para conectar; sin ellos la interfaz sigue siendo
  segura, pero no puede crear el túnel.

## Política de soporte

Los artefactos de este repositorio son una demostración técnica Linux y no
están afiliados con Cloudflare. Reporta problemas con versión de distribución,
arquitectura, versión de `warp-cli`, entorno de escritorio y pasos
reproducibles; no incluyas credenciales, identificadores de organización ni
registros sensibles.
