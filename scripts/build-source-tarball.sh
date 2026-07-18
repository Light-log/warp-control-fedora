#!/usr/bin/bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/.." && pwd)
version=$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$repo_root/pyproject.toml")

if [[ -z "$version" ]]; then
    echo "No se pudo leer la versión de pyproject.toml" >&2
    exit 1
fi

if ! git -C "$repo_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "El tarball de fuentes solo se crea desde un checkout Git" >&2
    exit 1
fi
if ! git -C "$repo_root" diff --quiet --ignore-submodules -- \
    || ! git -C "$repo_root" diff --cached --quiet --ignore-submodules --; then
    echo "El checkout contiene cambios sin confirmar; crea un commit antes del tarball" >&2
    exit 1
fi

source_date_epoch=${SOURCE_DATE_EPOCH:-$(git -C "$repo_root" show -s --format=%ct HEAD)}
if [[ ! "$source_date_epoch" =~ ^[0-9]+$ ]]; then
    echo "SOURCE_DATE_EPOCH debe ser un entero no negativo" >&2
    exit 1
fi

output=${1:-"$repo_root/dist/warp-control-$version.tar.gz"}
case "$output" in
    /*) ;;
    *) output="$PWD/$output" ;;
esac
output_dir=$(dirname -- "$output")
mkdir -p -- "$output_dir"
archive=$(mktemp "$output_dir/.warp-control-source.XXXXXX.tar.gz")
cleanup() {
    rm -f -- "$archive"
}
trap cleanup EXIT

git -C "$repo_root" archive \
    --format=tar \
    --prefix="warp-control-$version/" \
    --mtime="@$source_date_epoch" \
    HEAD \
    | gzip -n >"$archive"

mv -f -- "$archive" "$output"
trap - EXIT
printf '%s\n' "$output"
