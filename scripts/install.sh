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

lexical_absolute_path() {
    local input=$1 part result=""
    local -a components normalized=()
    [[ $input == /* ]] || input=$PWD/$input
    IFS='/' read -r -a components <<< "$input"
    for part in "${components[@]}"; do
        case $part in
            ''|.) ;;
            ..)
                ((${#normalized[@]} > 0)) || die "La ruta intenta salir de la raíz."
                unset 'normalized[${#normalized[@]}-1]'
                ;;
            *) normalized+=("$part") ;;
        esac
    done
    for part in "${normalized[@]}"; do
        result=$result/$part
    done
    printf '%s\n' "${result:-/}"
}

reject_symlink_chain() {
    local path=$1 label=$2 part current=""
    local -a components=()
    [[ $path == /* && $path != *$'\n'* && $path != *$'\r'* ]] || die "$label no es una ruta absoluta segura."
    IFS='/' read -r -a components <<< "$path"
    for part in "${components[@]}"; do
        [[ -n $part ]] || continue
        current=$current/$part
        [[ ! -L $current ]] || die "$label tiene un enlace simbólico en un ancestro: $current"
    done
}

validate_temp_base() {
    local base=$1 owner mode permissions
    reject_symlink_chain "$base" "La ruta temporal"
    [[ -d $base && -w $base ]] || die "La ruta temporal no es un directorio escribible: $base"
    owner=$(stat -c '%u' -- "$base")
    mode=$(stat -c '%a' -- "$base")
    [[ $mode =~ ^[0-7]{3,4}$ ]] || die "No se pudieron validar permisos de la ruta temporal."
    permissions=$((8#$mode))
    if [[ $owner == "$EUID" ]]; then
        (( (permissions & 0022) == 0 )) || die "La ruta temporal del usuario permite escritura a terceros."
    elif [[ $owner == 0 && $mode == 1777 ]]; then
        : # Temporal público administrado por raíz, protegido por sticky bit.
    elif [[ $base == /tmp && $mode == 1777 ]]; then
        : # Algunos contenedores sin privilegios mapean el uid 0 de /tmp a nobody.
    else
        die "La ruta temporal no pertenece al usuario ni es un temporal público seguro."
    fi
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

PACKAGE_PATH=$(lexical_absolute_path "$PACKAGE_PATH")
reject_symlink_chain "$PACKAGE_PATH" "El paquete fuente"
[[ ! -L $PACKAGE_PATH ]] || die "El paquete es un enlace simbólico; indica un archivo regular: $PACKAGE_PATH"
[[ -f $PACKAGE_PATH && -r $PACKAGE_PATH ]] || die "El paquete no existe o no se puede leer: $PACKAGE_PATH"

case $FAMILY:$PACKAGE_PATH in
    rpm:*.rpm) PACKAGE_KIND=rpm ;;
    debian:*.deb) PACKAGE_KIND=deb ;;
    arch:*.pkg.tar.*) PACKAGE_KIND=arch ;;
    rpm:*) die "La familia RPM requiere un paquete .rpm." ;;
    debian:*) die "La familia Debian requiere un paquete .deb." ;;
    arch:*) die "Arch requiere un paquete .pkg.tar.*." ;;
esac

if [[ ${XDG_RUNTIME_DIR:-} ]]; then
    runtime_candidate=$(lexical_absolute_path "$XDG_RUNTIME_DIR")
    reject_symlink_chain "$runtime_candidate" "La ruta temporal"
    if [[ -d $runtime_candidate && -w $runtime_candidate ]]; then
        TEMP_BASE=$runtime_candidate
    else
        TEMP_BASE=$(lexical_absolute_path "${TMPDIR:-/tmp}")
    fi
else
    TEMP_BASE=$(lexical_absolute_path "${TMPDIR:-/tmp}")
fi
validate_temp_base "$TEMP_BASE"
STAGING_DIR=$(mktemp -d -- "$TEMP_BASE/warp-control-install.XXXXXX")
chmod 0700 -- "$STAGING_DIR"
reject_symlink_chain "$STAGING_DIR" "El directorio temporal"
STAGING_ID=$(stat -c '%d:%i:%u' -- "$STAGING_DIR")
STAGED_PACKAGE=$STAGING_DIR/${PACKAGE_PATH##*/}

cleanup_staging() {
    local current_id=""
    if [[ -d ${STAGING_DIR:-} && ! -L $STAGING_DIR ]]; then
        current_id=$(stat -c '%d:%i:%u' -- "$STAGING_DIR" 2>/dev/null || true)
    fi
    if [[ $current_id == "${STAGING_ID:-invalid}" && -n ${STAGED_PACKAGE:-} && $STAGED_PACKAGE == "$STAGING_DIR"/* && -f $STAGED_PACKAGE && ! -L $STAGED_PACKAGE ]]; then
        rm -f -- "$STAGED_PACKAGE"
    fi
    if [[ $current_id == "${STAGING_ID:-invalid}" && -n ${STAGING_DIR:-} ]]; then
        rmdir -- "$STAGING_DIR" 2>/dev/null || true
    fi
}
trap cleanup_staging EXIT

cp -- "$PACKAGE_PATH" "$STAGED_PACKAGE"
[[ ! -L $PACKAGE_PATH ]] || die "El paquete fuente cambió a un enlace simbólico durante la copia."
[[ -f $STAGED_PACKAGE && ! -L $STAGED_PACKAGE ]] || die "No se pudo crear una instantánea regular del paquete."
chmod 0400 -- "$STAGED_PACKAGE"
SNAPSHOT_SIZE=$(wc -c < "$STAGED_PACKAGE")
read -r SNAPSHOT_SHA256 _ < <(sha256sum -- "$STAGED_PACKAGE")
[[ $SNAPSHOT_SHA256 =~ ^[0-9a-f]{64}$ ]] || die "No se pudo calcular SHA-256 de la instantánea."

case $PACKAGE_KIND in
    rpm) INSTALL_CMD=(sudo dnf install -y "$STAGED_PACKAGE") ;;
    deb) INSTALL_CMD=(sudo apt-get install -y "$STAGED_PACKAGE") ;;
    arch) INSTALL_CMD=(sudo pacman -U --needed "$STAGED_PACKAGE") ;;
esac

printf 'WARP Control — instalación por paquete nativo\n'
printf 'Sistema: %s\n' "$DISTRO_NAME"
printf 'Familia detectada: %s\n' "$FAMILY"
printf 'Paquete original: %s\n' "$PACKAGE_PATH"
printf 'Instantánea privada: %s bytes\n' "$SNAPSHOT_SIZE"
printf 'SHA-256: %s\n' "$SNAPSHOT_SHA256"
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

CURRENT_STAGING_ID=$(stat -c '%d:%i:%u' -- "$STAGING_DIR")
[[ $CURRENT_STAGING_ID == "$STAGING_ID" && -f $STAGED_PACKAGE && ! -L $STAGED_PACKAGE ]] || die "El directorio privado cambió después de la confirmación."
CURRENT_SIZE=$(wc -c < "$STAGED_PACKAGE")
read -r CURRENT_SHA256 _ < <(sha256sum -- "$STAGED_PACKAGE")
[[ $CURRENT_SIZE == "$SNAPSHOT_SIZE" && $CURRENT_SHA256 == "$SNAPSHOT_SHA256" ]] || die "La instantánea cambió después de la confirmación."

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
