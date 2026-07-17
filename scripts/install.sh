#!/usr/bin/env bash
set -Eeuo pipefail

PROGRAM=${0##*/}
DRY_RUN=0
ASSUME_YES=0
PACKAGE_PATH=""
OS_RELEASE=${WARP_CONTROL_OS_RELEASE:-/etc/os-release}

usage() {
    cat <<EOF
Uso: $PROGRAM [--dry-run] [--yes] [--package RUTA]

Instala un paquete nativo ya construido de WARP Control. Este bootstrap no
añade repositorios de terceros ni instala Cloudflare WARP silenciosamente.

  --package RUTA  usa un .rpm, .deb o .pkg.tar.* concreto
  --dry-run       muestra el plan sin pedir privilegios ni cambiar archivos
  --yes           acepta la instalación del paquete sin preguntar
  --help          muestra esta ayuda
EOF
}

die() {
    printf '[ERROR] %s\n' "$*" >&2
    exit 1
}

while (($#)); do
    case $1 in
        --package)
            (($# >= 2)) || die "--package requiere una ruta."
            PACKAGE_PATH=$2
            shift 2
            ;;
        --dry-run) DRY_RUN=1; shift ;;
        --yes|-y) ASSUME_YES=1; shift ;;
        --help|-h) usage; exit 0 ;;
        *) die "Opción desconocida: $1" ;;
    esac
done

if [[ ${WARP_CONTROL_OS_RELEASE+x} ]]; then
    [[ -f $OS_RELEASE && ! -L $OS_RELEASE ]] || die "os-release debe ser un archivo regular, no un enlace simbólico."
elif [[ -L $OS_RELEASE ]]; then
    OS_RELEASE=$(readlink -f -- "$OS_RELEASE")
fi
[[ -f $OS_RELEASE && ! -L $OS_RELEASE && -r $OS_RELEASE ]] || die "No se puede leer un os-release regular."
OS_RELEASE_SIZE=$(wc -c < "$OS_RELEASE")
[[ $OS_RELEASE_SIZE =~ ^[0-9]+$ && $OS_RELEASE_SIZE -le 65536 ]] || die "os-release supera el límite de 64 KiB."

# Leer únicamente campos simples de os-release, sin ejecutar su contenido.
DISTRO_ID=""
DISTRO_LIKE=""
DISTRO_NAME="Linux"
OS_RELEASE_LINES=0
while IFS='=' read -r key value; do
    OS_RELEASE_LINES=$((OS_RELEASE_LINES + 1))
    ((OS_RELEASE_LINES <= 256)) || die "os-release tiene demasiadas líneas."
    ((${#value} <= 4096)) || die "os-release contiene una línea demasiado larga."
    value=${value%$'\r'}
    if ((${#value} >= 2)) && [[ $value == \"*\" && $value == *\" ]]; then
        value=${value:1:${#value}-2}
    elif ((${#value} >= 2)) && [[ $value == \'*\' && $value == *\' ]]; then
        value=${value:1:${#value}-2}
    fi
    case $key in
        ID) DISTRO_ID=${value,,} ;;
        ID_LIKE) DISTRO_LIKE=${value,,} ;;
        PRETTY_NAME) DISTRO_NAME=$value ;;
    esac
done < "$OS_RELEASE"

ID_PATTERN='^[a-z0-9._-]+$'
ID_LIKE_PATTERN='^[a-z0-9._[:space:]-]+$'
[[ $DISTRO_ID =~ $ID_PATTERN ]] || die "ID no válido en os-release."
[[ -z $DISTRO_LIKE || $DISTRO_LIKE =~ $ID_LIKE_PATTERN ]] || die "ID_LIKE no válido en os-release."

case " $DISTRO_ID $DISTRO_LIKE " in
    *" arch "*|*" manjaro "*) FAMILY=arch ;;
    *" ubuntu "*|*" debian "*) FAMILY=debian ;;
    *" fedora "*|*" rhel "*|*" centos "*|*" rocky "*|*" almalinux "*)
        FAMILY=rpm
        ;;
    *) die "Distribución no soportada por el bootstrap: $DISTRO_NAME." ;;
esac

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
REPO_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd -P)

if [[ -z $PACKAGE_PATH ]]; then
    shopt -s nullglob
    case $FAMILY in
        rpm) candidates=("$REPO_DIR"/dist/*.rpm "$REPO_DIR"/packaging/rpm/RPMS/noarch/*.rpm) ;;
        debian) candidates=("$REPO_DIR"/dist/*.deb "$REPO_DIR"/../warp-control_*_all.deb) ;;
        arch) candidates=("$REPO_DIR"/dist/*.pkg.tar.* "$REPO_DIR"/*.pkg.tar.*) ;;
    esac
    shopt -u nullglob
    ((${#candidates[@]} == 1)) || {
        ((${#candidates[@]} > 1)) && die "Hay varios paquetes candidatos; usa --package RUTA."
        die "No se encontró un paquete nativo. Constrúyelo o indica --package RUTA."
    }
    PACKAGE_PATH=${candidates[0]}
fi

[[ ! -L $PACKAGE_PATH ]] || die "El paquete es un enlace simbólico; indica un archivo regular: $PACKAGE_PATH"
[[ -f $PACKAGE_PATH && -r $PACKAGE_PATH ]] || die "El paquete no existe o no se puede leer: $PACKAGE_PATH"
PACKAGE_PATH=$(cd -- "$(dirname -- "$PACKAGE_PATH")" && printf '%s/%s\n' "$PWD" "${PACKAGE_PATH##*/}")

case $FAMILY:$PACKAGE_PATH in
    rpm:*.rpm) INSTALL_CMD=(sudo dnf install -y "$PACKAGE_PATH") ;;
    debian:*.deb) INSTALL_CMD=(sudo apt-get install -y "$PACKAGE_PATH") ;;
    arch:*.pkg.tar.*) INSTALL_CMD=(sudo pacman -U --needed "$PACKAGE_PATH") ;;
    rpm:*) die "La familia RPM requiere un paquete .rpm." ;;
    debian:*) die "La familia Debian requiere un paquete .deb." ;;
    arch:*) die "Arch requiere un paquete .pkg.tar.*." ;;
esac

printf 'WARP Control — instalación por paquete nativo\n'
printf 'Sistema: %s\n' "$DISTRO_NAME"
printf 'Familia detectada: %s\n' "$FAMILY"
printf 'Paquete: %s\n' "$PACKAGE_PATH"
printf 'Acción privilegiada: '
printf '%q ' "${INSTALL_CMD[@]}"
printf '\n'

if [[ $FAMILY == arch ]]; then
    cat <<'EOF'

Cloudflare WARP en Arch es experimental y procede de la comunidad (AUR).
Este script no instalará WARP automáticamente. Consulta la documentación y
revisa el PKGBUILD comunitario antes de instalarlo.
EOF
else
    cat <<'EOF'

Este script solo instala WARP Control. Si falta Cloudflare WARP, la aplicación
mostrará el flujo oficial, explicará los cambios y pedirá autorización expresa.
EOF
fi

if ((DRY_RUN)); then
    printf '\n[DRY-RUN] No se solicitaron privilegios ni se modificó el sistema.\n'
    exit 0
fi

if ((!ASSUME_YES)); then
    [[ -t 0 ]] || die "Se necesita confirmación interactiva; usa --yes si ya revisaste el plan."
    read -r -p "¿Instalar este paquete? [s/N]: " answer
    [[ $answer == [sS] || $answer == [sS][iI] ]] || {
        printf 'Instalación cancelada.\n'
        exit 0
    }
fi

"${INSTALL_CMD[@]}"
printf '\n[OK] WARP Control fue instalado.\n'

if [[ -e $HOME/.local/lib/warp-control || -e $HOME/.local/bin/warp-control || -e $HOME/.local/share/applications/warp-control.desktop ]]; then
    printf 'Se detectó una instalación heredada. Revísala de forma segura con:\n  %q\n' "$SCRIPT_DIR/migrate-legacy.sh"
fi

if command -v warp-cli >/dev/null 2>&1; then
    printf 'Cloudflare WARP ya está disponible. Abre WARP Control desde el menú.\n'
else
    printf 'Cloudflare WARP no está instalado; WARP Control ofrecerá el flujo autorizado al abrirse.\n'
fi
