#!/usr/bin/env bash
set -Eeuo pipefail

PROGRAM=${0##*/}
APPLY=0
ASSUME_YES=0

usage() {
    cat <<EOF
Uso: $PROGRAM [--apply] [--yes]

Detecta archivos del instalador heredado. Por defecto solo muestra una vista
previa. --apply los mueve a una copia recuperable; nunca borra la configuración.
EOF
}

die() {
    printf '[ERROR] %s\n' "$*" >&2
    exit 1
}

while (($#)); do
    case $1 in
        --apply) APPLY=1; shift ;;
        --dry-run) APPLY=0; shift ;;
        --yes|-y) ASSUME_YES=1; shift ;;
        --help|-h) usage; exit 0 ;;
        *) die "Opción desconocida: $1" ;;
    esac
done

[[ -n ${HOME:-} && $HOME == /* && $HOME != / ]] || die "HOME no es una ruta absoluta segura."
[[ -d $HOME && ! -L $HOME ]] || die "HOME no existe o es un enlace simbólico."

LOCAL_ROOT=$HOME/.local
[[ ! -L $LOCAL_ROOT ]] || die "$LOCAL_ROOT es un enlace simbólico; migración cancelada."

targets=(
    "$LOCAL_ROOT/lib/warp-control"
    "$LOCAL_ROOT/bin/warp-control"
    "$LOCAL_ROOT/share/applications/warp-control.desktop"
)
relative=(
    "lib/warp-control"
    "bin/warp-control"
    "share/applications/warp-control.desktop"
)

AUTOSTART_FILE=$HOME/.config/autostart/warp-control.desktop
if [[ -e $AUTOSTART_FILE || -L $AUTOSTART_FILE ]]; then
    autostart_parent=${AUTOSTART_FILE%/*}
    while [[ $autostart_parent == "$HOME"/* ]]; do
        [[ ! -L $autostart_parent ]] || die "$autostart_parent es un enlace simbólico; migración cancelada."
        autostart_parent=${autostart_parent%/*}
    done
    [[ ! -L $AUTOSTART_FILE ]] || die "$AUTOSTART_FILE es un enlace simbólico; migración cancelada."
    [[ -f $AUTOSTART_FILE && -r $AUTOSTART_FILE ]] || die "$AUTOSTART_FILE no es un archivo regular legible."
    autostart_size=$(wc -c < "$AUTOSTART_FILE")
    [[ $autostart_size =~ ^[0-9]+$ && $autostart_size -le 65536 ]] || die "El autostart supera el límite seguro."
    exec_value=""
    exec_count=0
    while IFS= read -r desktop_line || [[ -n $desktop_line ]]; do
        desktop_line=${desktop_line%$'\r'}
        if [[ $desktop_line == Exec=* ]]; then
            exec_count=$((exec_count + 1))
            exec_value=${desktop_line#Exec=}
        fi
    done < "$AUTOSTART_FILE"
    legacy_launcher=$LOCAL_ROOT/bin/warp-control
    if ((exec_count == 1)) && { [[ $exec_value == "$legacy_launcher" ]] || [[ $exec_value == "$legacy_launcher "* ]]; }; then
        targets+=("$AUTOSTART_FILE")
        relative+=("config/autostart/warp-control.desktop")
    fi
fi

found=()
found_relative=()
for index in "${!targets[@]}"; do
    target=${targets[$index]}
    parent=${target%/*}
    while [[ $parent == "$LOCAL_ROOT"/* ]]; do
        [[ ! -L $parent ]] || die "$parent es un enlace simbólico; migración cancelada."
        parent=${parent%/*}
    done
    if [[ -e $target || -L $target ]]; then
        [[ ! -L $target ]] || die "$target es un enlace simbólico; migración cancelada."
        found+=("$target")
        found_relative+=("${relative[$index]}")
    fi
done

printf 'WARP Control — migración de instalación heredada\n'
printf 'La configuración se conserva: %s\n' "$HOME/.config/warp-control/config.json"

if ((${#found[@]} == 0)); then
    printf 'No se encontraron rutas heredadas conocidas.\n'
    exit 0
fi

printf '\nRutas exactas detectadas:\n'
printf '  %s\n' "${found[@]}"

if ((!APPLY)); then
    printf '\nVista previa: no se modificó nada. Ejecuta %q --apply para crear una copia y migrar.\n' "$0"
    exit 0
fi

if ((!ASSUME_YES)); then
    [[ -t 0 ]] || die "Se necesita confirmación interactiva; usa --yes tras revisar la lista."
    read -r -p "¿Mover estas rutas a una copia recuperable? [s/N]: " answer
    [[ $answer == [sS] || $answer == [sS][iI] ]] || {
        printf 'Migración cancelada.\n'
        exit 0
    }
fi

timestamp=${WARP_CONTROL_TIMESTAMP:-$(date -u +%Y%m%dT%H%M%SZ)}
[[ $timestamp =~ ^[A-Za-z0-9._-]+$ ]] || die "Identificador de copia no válido."
BACKUP_ROOT=$LOCAL_ROOT/state/warp-control/legacy-backups/$timestamp
[[ ! -e $BACKUP_ROOT && ! -L $BACKUP_ROOT ]] || die "La copia ya existe: $BACKUP_ROOT"

backup_parent=$BACKUP_ROOT
while [[ $backup_parent == "$LOCAL_ROOT"/* ]]; do
    [[ ! -L $backup_parent ]] || die "$backup_parent es un enlace simbólico; migración cancelada."
    backup_parent=${backup_parent%/*}
done

# Validar todo antes de crear directorios o mover la primera ruta.
for target in "${found[@]}"; do
    [[ $target == "$LOCAL_ROOT"/* || $target == "$AUTOSTART_FILE" ]] || die "Ruta insegura: $target"
    [[ ! -L $target ]] || die "Ruta insegura: $target"
done

mkdir -p -- "$BACKUP_ROOT"
moved_count=0
rollback_moves() {
    status=$?
    trap - ERR
    set +e
    while ((moved_count > 0)); do
        index=$((moved_count - 1))
        destination=$BACKUP_ROOT/${found_relative[$index]}
        if [[ -e $destination && ! -e ${found[$index]} ]]; then
            mv -- "$destination" "${found[$index]}"
        fi
        moved_count=$index
    done
    printf '[ERROR] La migración falló; los movimientos completados se revirtieron.\n' >&2
    exit "$status"
}
trap rollback_moves ERR

for index in "${!found[@]}"; do
    destination=$BACKUP_ROOT/${found_relative[$index]}
    mkdir -p -- "${destination%/*}"
    mv -- "${found[$index]}" "$destination"
    moved_count=$((moved_count + 1))
done

{
    printf 'WARP Control legacy migration backup\n'
    printf 'Configuration preserved: %s\n' "$HOME/.config/warp-control/config.json"
    printf 'Moved path: %s\n' "${found_relative[@]}"
} > "$BACKUP_ROOT/MANIFEST.txt"
trap - ERR

printf '\n[OK] Instalación heredada movida a:\n  %s\n' "$BACKUP_ROOT"
printf 'La configuración y la instalación actual del sistema no fueron modificadas.\n'
