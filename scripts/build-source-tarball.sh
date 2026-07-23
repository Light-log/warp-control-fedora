#!/usr/bin/bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/.." && pwd)

pyproject_version=$(sed -n 's/^version = "\([^"]*\)"$/\1/p' "$repo_root/pyproject.toml")
if [[ ! "$pyproject_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Could not read version from pyproject.toml" >&2
    exit 1
fi

release_env="$repo_root/packaging/release.env"
if [[ ! -f "$release_env" ]]; then
    echo "release.env not found: $release_env" >&2
    exit 1
fi

env_version=''
release_epoch=''
while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
        VERSION=*)
            [[ -z "$env_version" ]] || { echo "duplicate VERSION in release.env" >&2; exit 1; }
            env_version=${line#VERSION=}
            ;;
        SOURCE_DATE_EPOCH=*)
            [[ -z "$release_epoch" ]] || { echo "duplicate SOURCE_DATE_EPOCH in release.env" >&2; exit 1; }
            release_epoch=${line#SOURCE_DATE_EPOCH=}
            ;;
        *)
            echo "invalid release.env data" >&2
            exit 1
            ;;
    esac
done < "$release_env"

if [[ ! "$env_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ || ! "$release_epoch" =~ ^[0-9]+$ ]]; then
    echo "release.env must define a semantic VERSION and non-negative SOURCE_DATE_EPOCH" >&2
    exit 1
fi

if [[ "$env_version" != "$pyproject_version" ]]; then
    echo "Version mismatch: release.env=$env_version != pyproject.toml=$pyproject_version" >&2
    exit 1
fi

if ! git -C "$repo_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Source tarball can only be created from a git checkout" >&2
    exit 1
fi

if ! git -C "$repo_root" diff --quiet --ignore-submodules -- \
    || ! git -C "$repo_root" diff --cached --quiet --ignore-submodules --; then
    echo "Checkout contains uncommitted changes; commit before creating tarball" >&2
    exit 1
fi

if [[ -n "${SOURCE_DATE_EPOCH:-}" ]]; then
    source_date_epoch="$SOURCE_DATE_EPOCH"
else
    source_date_epoch="$release_epoch"
fi

if [[ ! "$source_date_epoch" =~ ^[0-9]+$ ]]; then
    echo "SOURCE_DATE_EPOCH must be a non-negative integer" >&2
    exit 1
fi

version="$pyproject_version"
output=${1:-"$repo_root/dist/warp-control-$version.tar.gz"}
case "$output" in
    /*) ;;
    *) output="$PWD/$output" ;;
esac
output_dir=$(dirname -- "$output")
mkdir -p -- "$output_dir"
archive=$(mktemp "$output_dir/.warp-control-source.XXXXXX.tar.gz")
source_tree=''
cleanup() {
    rm -f -- "$archive"
    if [[ -n "$source_tree" ]]; then
        rm -rf -- "$source_tree"
    fi
}
trap cleanup EXIT
source_tree=$(mktemp -d "$output_dir/.warp-control-source-tree.XXXXXX")

git -C "$repo_root" archive \
    --format=tar \
    --prefix="warp-control-$version/" \
    HEAD \
    ':!packaging/arch/PKGBUILD' \
    | tar -C "$source_tree" --extract --file=-

tar -C "$source_tree" \
        --create \
        --format=posix \
        --sort=name \
        --mtime="@$source_date_epoch" \
        --owner=0 \
        --group=0 \
        --numeric-owner \
        --pax-option=delete=atime,delete=ctime \
        "warp-control-$version" \
    | gzip -n >"$archive"

mv -f -- "$archive" "$output"
printf '%s\n' "$output"
