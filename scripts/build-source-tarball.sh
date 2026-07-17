#!/usr/bin/bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/.." && pwd)
version=$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$repo_root/pyproject.toml")

if [[ -z "$version" ]]; then
    echo "No se pudo leer la versión de pyproject.toml" >&2
    exit 1
fi

output=${1:-"$repo_root/dist/warp-control-$version.tar.gz"}
case "$output" in
    /*) ;;
    *) output="$PWD/$output" ;;
esac
output_dir=$(dirname -- "$output")
mkdir -p -- "$output_dir"

source_date_epoch=${SOURCE_DATE_EPOCH:-$(git -C "$repo_root" show -s --format=%ct HEAD)}
if [[ ! "$source_date_epoch" =~ ^[0-9]+$ ]]; then
    echo "SOURCE_DATE_EPOCH debe ser un entero no negativo" >&2
    exit 1
fi

file_list=$(mktemp)
archive=$(mktemp "$output_dir/.warp-control-source.XXXXXX.tar.gz")
cleanup() {
    rm -f -- "$file_list" "$archive"
}
trap cleanup EXIT

if git -C "$repo_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -C "$repo_root" ls-files --cached --others --exclude-standard -z \
        | LC_ALL=C sort -z >"$file_list"
else
    while IFS= read -r -d '' path; do
        printf '%s\0' "${path#./}"
    done < <(
        cd -- "$repo_root"
        find . \
            -type d \( \
                -name .git -o -name .venv -o -name build -o -name dist \
                -o -name .pytest_cache -o -name .ruff_cache \
                -o -name __pycache__ -o -name '*.egg-info' \
            \) -prune -o \( -type f -o -type l \) -print0
    ) | LC_ALL=C sort -z >"$file_list"
fi

tar -C "$repo_root" \
    --null \
    --files-from="$file_list" \
    --sort=name \
    --format=posix \
    --pax-option=delete=atime,delete=ctime \
    --mtime="@$source_date_epoch" \
    --owner=0 \
    --group=0 \
    --numeric-owner \
    --transform="s,^,warp-control-$version/," \
    -cf - \
    | gzip -n >"$archive"

mv -f -- "$archive" "$output"
trap - EXIT
rm -f -- "$file_list"
printf '%s\n' "$output"
