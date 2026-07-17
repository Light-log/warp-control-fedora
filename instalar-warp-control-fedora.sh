#!/usr/bin/env bash
set -Eeuo pipefail

# Nombre conservado para quienes guardaron el instalador anterior. La aplicación
# y sus recursos viven ahora en el paquete nativo; este archivo solo delega.
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
exec "$SCRIPT_DIR/scripts/install.sh" "$@"
