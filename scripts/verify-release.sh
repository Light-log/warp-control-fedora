#!/usr/bin/env bash
set -euo pipefail

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

[[ $# -eq 2 ]] || fail "usage: verify-release.sh TAG RELEASE_DIR"
tag=$1
release_dir=$2
[[ $tag =~ ^v([0-9]+\.[0-9]+\.[0-9]+)$ ]] || fail "tag must match vMAJOR.MINOR.PATCH"
tag_version=${BASH_REMATCH[1]}

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=$(cd -- "$script_dir/.." && pwd -P)
[[ ! -L $release_dir && -d $release_dir ]] || fail "release directory must be a real directory"
release_dir=$(cd -- "$release_dir" && pwd -P)

single_value() {
    local file=$1 pattern=$2 label=$3
    local -a matches=()
    mapfile -t matches < <(sed -nE "s/${pattern}/\\1/p" "$file")
    [[ ${#matches[@]} -eq 1 && -n ${matches[0]} ]] || \
        fail "$label must occur exactly once"
    printf '%s\n' "${matches[0]}"
}

release_version=$(single_value \
    "$repo_root/packaging/release.env" '^VERSION=([^=]+)$' 'release.env VERSION')
pyproject_version=$(single_value \
    "$repo_root/pyproject.toml" '^version = "([^"]+)"$' 'pyproject version')
rpm_version=$(single_value \
    "$repo_root/packaging/rpm/warp-control.spec" '^Version:[[:space:]]*([^[:space:]]+)$' 'RPM version')
rpm_release=$(single_value \
    "$repo_root/packaging/rpm/warp-control.spec" '^Release:[[:space:]]*([0-9]+)%\{\?dist\}$' 'RPM release')
IFS= read -r debian_header < "$repo_root/debian/changelog" || \
    fail "Debian changelog must have a current entry"
debian_header_pattern='^warp-control \(([^)]+)\) .+$'
[[ $debian_header =~ $debian_header_pattern ]] || \
    fail "Debian changelog must start with the current warp-control entry"
debian_full_version=${BASH_REMATCH[1]}
[[ $debian_full_version =~ ^([0-9]+\.[0-9]+\.[0-9]+)-([0-9]+)$ ]] || \
    fail "Debian version must be MAJOR.MINOR.PATCH-REVISION"
debian_version=${BASH_REMATCH[1]}
debian_revision=${BASH_REMATCH[2]}
arch_version=$(single_value \
    "$repo_root/packaging/arch/PKGBUILD" '^pkgver=([^[:space:]]+)$' 'PKGBUILD pkgver')
arch_release=$(single_value \
    "$repo_root/packaging/arch/PKGBUILD" '^pkgrel=([0-9]+)$' 'PKGBUILD pkgrel')

for metadata_version in \
    "$release_version" "$pyproject_version" "$rpm_version" \
    "$debian_version" "$arch_version"; do
    [[ $metadata_version == "$tag_version" ]] || \
        fail "version mismatch: tag is $tag_version but metadata contains $metadata_version"
done

required=(
    "warp-control-$tag_version.tar.gz"
    "warp-control-$tag_version-$rpm_release.fc43.noarch.rpm"
    "warp-control-$tag_version-$rpm_release.fc44.noarch.rpm"
    "warp-control-$tag_version-$rpm_release.el9.noarch.rpm"
    "warp-control-$tag_version-$rpm_release.el10.noarch.rpm"
    "warp-control_${tag_version}-${debian_revision}_all-ubuntu2204.deb"
    "warp-control_${tag_version}-${debian_revision}_all-ubuntu2404.deb"
    "warp-control_${tag_version}-${debian_revision}_all-ubuntu2604.deb"
    "warp-control_${tag_version}-${debian_revision}_all-debian12.deb"
    "warp-control_${tag_version}-${debian_revision}_all-debian13.deb"
    "warp-control-$tag_version-$arch_release-any.pkg.tar.zst"
    "WARP-Control-$tag_version-x86_64.AppImage"
    "WARP-Control-$tag_version-aarch64.AppImage"
)

if find "$release_dir" -mindepth 1 -type l -print -quit | grep -q .; then
    fail "release inputs must not contain symlinks"
fi
if find "$release_dir" -mindepth 1 ! -type d ! -type f ! -type l -print -quit | grep -q .; then
    fail "release inputs must be regular files"
fi

declare -A artifact_paths=()
while IFS= read -r -d '' path; do
    [[ $path == "$release_dir/SHA256SUMS" ]] && continue
    name=${path##*/}
    [[ -z ${artifact_paths[$name]+present} ]] || fail "duplicate artifact basename: $name"
    artifact_paths[$name]=$path
done < <(find "$release_dir" -mindepth 1 -type f -print0)

declare -A required_names=()
for name in "${required[@]}"; do
    required_names[$name]=1
    [[ -n ${artifact_paths[$name]+present} ]] || fail "missing required artifact: $name"
done
for name in "${!artifact_paths[@]}"; do
    [[ -n ${required_names[$name]+present} ]] || fail "unexpected release artifact: $name"
done

manifest=$release_dir/SHA256SUMS
if [[ -e $manifest ]]; then
    [[ ! -L $manifest && -f $manifest ]] || fail "SHA256SUMS must be a regular file"
    declare -A recorded=()
    while IFS= read -r line || [[ -n $line ]]; do
        [[ $line =~ ^([0-9a-f]{64})\ \ ([^/]+)$ ]] || fail "invalid checksum manifest"
        digest=${BASH_REMATCH[1]}
        name=${BASH_REMATCH[2]}
        [[ -z ${recorded[$name]+present} ]] || fail "duplicate checksum entry: $name"
        recorded[$name]=$digest
    done < "$manifest"
    for name in "${required[@]}"; do
        [[ -n ${recorded[$name]+present} ]] || fail "checksum missing for $name"
        actual=$(sha256sum -- "${artifact_paths[$name]}")
        actual=${actual%% *}
        [[ ${recorded[$name]} == "$actual" ]] || fail "checksum mismatch for $name"
    done
    [[ ${#recorded[@]} -eq ${#required[@]} ]] || fail "unexpected checksum entry"
fi

temporary=$(mktemp -- "$release_dir/.SHA256SUMS.XXXXXXXX")
trap 'rm -f -- "$temporary"' EXIT
while IFS= read -r name; do
    digest=$(sha256sum -- "${artifact_paths[$name]}")
    printf '%s  %s\n' "${digest%% *}" "$name"
done < <(printf '%s\n' "${required[@]}" | LC_ALL=C sort) > "$temporary"
chmod 0644 "$temporary"
mv -fT -- "$temporary" "$manifest"
trap - EXIT
printf 'Verified release %s (%s artifacts)\n' "$tag" "${#required[@]}"
