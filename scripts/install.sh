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

Instala un paquete nativo o integra un AppImage de WARP Control. Este
bootstrap no añade repositorios de terceros ni instala Cloudflare WARP
silenciosamente.

  --package RUTA  usa un .rpm, .deb, .pkg.tar.* o .AppImage concreto
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

appimage_header_arch() {
    local image=$1 magic elf_class byte_order machine
    magic=$(od -An -tx1 -N4 -- "$image" 2>/dev/null | tr -d ' \n')
    elf_class=$(od -An -tx1 -j4 -N1 -- "$image" 2>/dev/null | tr -d ' \n')
    byte_order=$(od -An -tx1 -j5 -N1 -- "$image" 2>/dev/null | tr -d ' \n')
    machine=$(od -An -tx1 -j18 -N2 -- "$image" 2>/dev/null | tr -d ' \n')
    [[ $magic == 7f454c46 && $elf_class == 02 && $byte_order == 01 ]] || return 1
    case $machine in
        3e00) printf 'x86_64\n' ;;
        b700) printf 'aarch64\n' ;;
        *) return 1 ;;
    esac
}

appimage_cleanup_staging() {
    local current_id=""
    [[ ${APPIMAGE_RETAIN_STAGING:-0} == 0 ]] || return 0
    if [[ -d ${APPIMAGE_STAGING_DIR:-} && ! -L $APPIMAGE_STAGING_DIR ]]; then
        current_id=$(stat -c '%d:%i:%u' -- "$APPIMAGE_STAGING_DIR" 2>/dev/null || true)
    fi
    if [[ $current_id == "${APPIMAGE_STAGING_ID:-invalid}" && ${APPIMAGE_STAGING_DIR:-} == "${TEMP_BASE:-/invalid}"/warp-control-appimage.* ]]; then
        rm -rf --one-file-system -- "$APPIMAGE_STAGING_DIR"
    fi
}

desktop_exec_value() {
    local value=$1
    if [[ $value =~ ^[A-Za-z0-9_./:+@%-]+$ ]]; then
        printf '%s' "$value"
    else
        value=${value//\\/\\\\}
        value=${value//\"/\\\"}
        value=${value//\`/\\\`}
        value=${value//\$/\\$}
        printf '"%s"' "$value"
    fi
}

is_managed_appimage_launcher() {
    local launcher=$1 opt_dir=$2 escaped_opt target_token suffix=' "$@"'
    local -a lines=()
    mapfile -t lines < "$launcher"
    ((${#lines[@]} == 2)) || return 1
    [[ ${lines[0]} == '#!/usr/bin/env bash' ]] || return 1
    [[ ${lines[1]} == exec\ *"$suffix" ]] || return 1
    target_token=${lines[1]#exec }
    target_token=${target_token%"$suffix"}
    [[ ${lines[1]} == "exec $target_token$suffix" ]] || return 1
    printf -v escaped_opt '%q' "$opt_dir/"
    [[ $target_token == "$escaped_opt"* ]] || return 1
    target_token=${target_token#"$escaped_opt"}
    [[ $target_token =~ ^WARP-Control-([0-9][A-Za-z0-9._+-]*|local)-(x86_64|aarch64)\.AppImage$ ]]
}

install_appimage() {
    local source=$1 host_arch image_arch install_root image_name
    local opt_dir bin_dir desktop_dir icon_dir image_target launcher_target desktop_target icon_target
    local snapshot desktop_source icon_source desktop_exec line exec_count=0
    local -a desktop_matches=() icon_matches=() targets=() candidates=() backups=() modes=()
    local index replaced=0 candidate rollback_failed
    local source_owner source_mode source_permissions

    source=$(lexical_absolute_path "$source")
    reject_symlink_chain "$source" "El AppImage fuente"
    [[ ! -L $source && -f $source && -r $source ]] || die "El AppImage no es un archivo regular legible: $source"
    source_owner=$(stat -c '%u' -- "$source")
    source_mode=$(stat -c '%a' -- "$source")
    [[ $source_mode =~ ^[0-7]{3,4}$ ]] || die "No se pudieron validar los permisos del AppImage."
    source_permissions=$((8#$source_mode))
    [[ $source_owner == "$EUID" || $source_owner == 0 ]] || die "El AppImage debe pertenecer al usuario actual o a root."
    (( (source_permissions & 0022) == 0 )) || die "El AppImage permite escritura de grupo o terceros y no es seguro."
    image_arch=$(appimage_header_arch "$source") || die "El archivo .AppImage no tiene un encabezado ELF64 little-endian compatible."
    case $(uname -m) in
        x86_64|amd64) host_arch=x86_64 ;;
        aarch64|arm64) host_arch=aarch64 ;;
        *) die "La arquitectura del equipo no admite este AppImage." ;;
    esac
    [[ $image_arch == "$host_arch" ]] || die "El AppImage es para $image_arch, pero el equipo es $host_arch."

    install_root=${WARP_CONTROL_INSTALL_ROOT:-$HOME/.local}
    [[ $install_root == /* ]] || die "WARP_CONTROL_INSTALL_ROOT debe ser una ruta absoluta."
    install_root=$(lexical_absolute_path "$install_root")
    [[ $install_root != *$'\n'* && $install_root != *$'\r'* ]] || die "La raíz de instalación no es segura."
    reject_symlink_chain "$install_root" "La raíz de instalación"

    image_name=${source##*/}
    if [[ ! $image_name =~ ^WARP-Control-[0-9][A-Za-z0-9._+-]*-${image_arch}\.AppImage$ ]]; then
        image_name=WARP-Control-local-${image_arch}.AppImage
    fi
    opt_dir=$install_root/opt/warp-control
    bin_dir=$install_root/bin
    desktop_dir=$install_root/share/applications
    icon_dir=$install_root/share/icons/hicolor/scalable/apps
    image_target=$opt_dir/$image_name
    launcher_target=$bin_dir/warp-control
    desktop_target=$desktop_dir/com.devruby.warpcontrol.desktop
    icon_target=$icon_dir/com.devruby.warpcontrol.svg

    if [[ ${XDG_RUNTIME_DIR:-} ]]; then
        TEMP_BASE=$(lexical_absolute_path "$XDG_RUNTIME_DIR")
        if [[ ! -d $TEMP_BASE || ! -w $TEMP_BASE ]]; then
            TEMP_BASE=$(lexical_absolute_path "${TMPDIR:-/tmp}")
        fi
    else
        TEMP_BASE=$(lexical_absolute_path "${TMPDIR:-/tmp}")
    fi
    validate_temp_base "$TEMP_BASE"
    APPIMAGE_STAGING_DIR=$(mktemp -d -- "$TEMP_BASE/warp-control-appimage.XXXXXX")
    chmod 0700 -- "$APPIMAGE_STAGING_DIR"
    reject_symlink_chain "$APPIMAGE_STAGING_DIR" "El directorio temporal"
    APPIMAGE_STAGING_ID=$(stat -c '%d:%i:%u' -- "$APPIMAGE_STAGING_DIR")
    APPIMAGE_RETAIN_STAGING=0
    trap appimage_cleanup_staging EXIT

    snapshot=$APPIMAGE_STAGING_DIR/$image_name
    cp -- "$source" "$snapshot"
    [[ ! -L $source && -f $snapshot && ! -L $snapshot ]] || die "El AppImage cambió durante la instantánea."
    chmod 0500 -- "$snapshot"
    read -r SNAPSHOT_SHA256 _ < <(sha256sum -- "$snapshot")

    printf 'WARP Control — instalación local AppImage\n'
    printf 'Arquitectura: %s\n' "$image_arch"
    printf 'AppImage original: %s\n' "$source"
    printf 'Destino: %s\n' "$image_target"
    printf 'Lanzador: %s\n' "$launcher_target"
    printf 'SHA-256: %s\n' "$SNAPSHOT_SHA256"
    printf 'Acción privilegiada: ninguna\n'
    if ((DRY_RUN)); then
        printf '\n[DRY-RUN] No se solicitaron privilegios ni se modificó el sistema.\n'
        exit 0
    fi

    if ((!ASSUME_YES)); then
        [[ -t 0 ]] || die "Se necesita confirmación interactiva; usa --yes si ya revisaste el plan."
        read -r -p "¿Instalar este AppImage para el usuario actual? [s/N]: " answer
        [[ $answer == [sS] || $answer == [sS][iI] ]] || {
            printf 'Instalación cancelada.\n'
            exit 0
        }
    fi

    mkdir "$APPIMAGE_STAGING_DIR/desktop" "$APPIMAGE_STAGING_DIR/icon"
    (cd -- "$APPIMAGE_STAGING_DIR/desktop" && "$snapshot" --appimage-extract '*.desktop' >/dev/null)
    (cd -- "$APPIMAGE_STAGING_DIR/icon" && "$snapshot" --appimage-extract 'usr/share/icons/hicolor/scalable/apps/*.svg' >/dev/null)
    shopt -s nullglob globstar
    desktop_matches=("$APPIMAGE_STAGING_DIR"/desktop/squashfs-root/*.desktop)
    icon_matches=("$APPIMAGE_STAGING_DIR"/icon/squashfs-root/usr/share/icons/hicolor/scalable/apps/*.svg)
    shopt -u nullglob globstar
    ((${#desktop_matches[@]} == 1)) || die "El AppImage no contiene exactamente un archivo desktop esperado."
    ((${#icon_matches[@]} == 1)) || die "El AppImage no contiene exactamente un icono SVG esperado."
    desktop_source=${desktop_matches[0]}
    icon_source=${icon_matches[0]}
    [[ -f $desktop_source && ! -L $desktop_source ]] || die "El archivo desktop extraído no es regular."
    [[ -f $icon_source && ! -L $icon_source ]] || die "El icono extraído no es regular."

    desktop_exec=$(desktop_exec_value "$launcher_target")
    while IFS= read -r line || [[ -n $line ]]; do
        if [[ $line == Exec=* ]]; then
            printf 'Exec=%s\n' "$desktop_exec"
            exec_count=$((exec_count + 1))
        else
            printf '%s\n' "$line"
        fi
    done < "$desktop_source" > "$APPIMAGE_STAGING_DIR/com.devruby.warpcontrol.desktop"
    ((exec_count == 1)) || die "El archivo desktop debe contener exactamente una línea Exec."
    cp -- "$icon_source" "$APPIMAGE_STAGING_DIR/com.devruby.warpcontrol.svg"
    {
        printf '#!/usr/bin/env bash\nexec '
        printf '%q' "$image_target"
        printf ' "$@"\n'
    } > "$APPIMAGE_STAGING_DIR/warp-control"
    chmod 0755 -- "$APPIMAGE_STAGING_DIR/warp-control"

    if [[ -e $launcher_target || -L $launcher_target ]]; then
        reject_symlink_chain "$launcher_target" "El lanzador existente"
        [[ -f $launcher_target && ! -L $launcher_target ]] || die "El lanzador existente no es un archivo regular seguro."
        is_managed_appimage_launcher "$launcher_target" "$opt_dir" || die "El lanzador existente pertenece a otra instalación y no se reemplazará."
    fi

    mkdir -p -- "$opt_dir" "$bin_dir" "$desktop_dir" "$icon_dir"
    for candidate in "$opt_dir" "$bin_dir" "$desktop_dir" "$icon_dir"; do
        reject_symlink_chain "$candidate" "El directorio de instalación"
        [[ -d $candidate && ! -L $candidate ]] || die "El destino de instalación no es un directorio regular."
    done

    targets=("$image_target" "$launcher_target" "$desktop_target" "$icon_target")
    candidates=("$opt_dir/.warp-control.image.$$" "$bin_dir/.warp-control.launcher.$$" "$desktop_dir/.warp-control.desktop.$$" "$icon_dir/.warp-control.icon.$$")
    backups=("$APPIMAGE_STAGING_DIR/backup-image" "$APPIMAGE_STAGING_DIR/backup-launcher" "$APPIMAGE_STAGING_DIR/backup-desktop" "$APPIMAGE_STAGING_DIR/backup-icon")
    modes=(0755 0755 0644 0644)
    for index in "${!targets[@]}"; do
        reject_symlink_chain "${targets[$index]}" "El destino de instalación"
        [[ ! -e ${candidates[$index]} && ! -L ${candidates[$index]} ]] || die "Existe un archivo temporal inesperado en el destino."
        if [[ -e ${targets[$index]} || -L ${targets[$index]} ]]; then
            [[ -f ${targets[$index]} && ! -L ${targets[$index]} ]] || die "Un destino existente no es un archivo regular seguro."
            cp -p -- "${targets[$index]}" "${backups[$index]}"
        fi
    done
    cp -- "$snapshot" "${candidates[0]}"
    cp -- "$APPIMAGE_STAGING_DIR/warp-control" "${candidates[1]}"
    cp -- "$APPIMAGE_STAGING_DIR/com.devruby.warpcontrol.desktop" "${candidates[2]}"
    cp -- "$APPIMAGE_STAGING_DIR/com.devruby.warpcontrol.svg" "${candidates[3]}"
    for index in "${!candidates[@]}"; do
        chmod "${modes[$index]}" -- "${candidates[$index]}"
    done

    for index in "${!targets[@]}"; do
        if ! mv -f -- "${candidates[$index]}" "${targets[$index]}"; then
            rollback_failed=0
            for ((replaced = index - 1; replaced >= 0; replaced--)); do
                if [[ -f ${backups[$replaced]} ]]; then
                    if ! cp -p -- "${backups[$replaced]}" "${candidates[$replaced]}"; then
                        rollback_failed=1
                        APPIMAGE_RETAIN_STAGING=1
                    elif ! mv -f -- "${candidates[$replaced]}" "${targets[$replaced]}"; then
                        rollback_failed=1
                        APPIMAGE_RETAIN_STAGING=1
                    fi
                else
                    if ! rm -f -- "${targets[$replaced]}"; then
                        rollback_failed=1
                        APPIMAGE_RETAIN_STAGING=1
                    fi
                fi
            done
            for candidate in "${candidates[@]}"; do
                if [[ -f $candidate && ! -L $candidate ]]; then
                    if ! rm -f -- "$candidate"; then
                        rollback_failed=1
                        APPIMAGE_RETAIN_STAGING=1
                    fi
                fi
            done
            if ((rollback_failed)); then
                die "La instalación falló y la restauración quedó incompleta. Copias de recuperación: $APPIMAGE_STAGING_DIR"
            fi
            die "No se pudo completar la sustitución atómica; se restauró la instalación anterior."
        fi
    done

    printf '\n[OK] WARP Control fue instalado localmente sin privilegios.\n'
    exit 0
}

# Un AppImage explícito se identifica y valida antes de leer la familia de la
# distribución. Así también funciona en distribuciones no incluidas en la
# matriz de paquetes nativos.
if [[ -n $PACKAGE_PATH && $PACKAGE_PATH == *.AppImage ]]; then
    install_appimage "$PACKAGE_PATH"
fi

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
