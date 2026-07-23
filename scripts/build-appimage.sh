#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat >&2 <<'EOF'
Usage: scripts/build-appimage.sh --arch x86_64|aarch64 --appimagetool PATH --runtime-file PATH --output-dir ABSOLUTE_PATH
EOF
}

fail_usage() {
    printf 'Error: %s\n' "$1" >&2
    usage
    exit 2
}

arch=""
appimagetool=""
runtime_file=""
output_dir=""
seen_arch=0
seen_tool=0
seen_runtime=0
seen_output=0

while (( $# > 0 )); do
    case "$1" in
        --arch)
            (( $# >= 2 )) || fail_usage "--arch requires a value"
            (( seen_arch == 0 )) || fail_usage "--arch may be specified only once"
            arch=$2
            seen_arch=1
            shift 2
            ;;
        --appimagetool)
            (( $# >= 2 )) || fail_usage "--appimagetool requires a value"
            (( seen_tool == 0 )) || fail_usage "--appimagetool may be specified only once"
            appimagetool=$2
            seen_tool=1
            shift 2
            ;;
        --runtime-file)
            (( $# >= 2 )) || fail_usage "--runtime-file requires a value"
            (( seen_runtime == 0 )) || fail_usage "--runtime-file may be specified only once"
            runtime_file=$2
            seen_runtime=1
            shift 2
            ;;
        --output-dir)
            (( $# >= 2 )) || fail_usage "--output-dir requires a value"
            (( seen_output == 0 )) || fail_usage "--output-dir may be specified only once"
            output_dir=$2
            seen_output=1
            shift 2
            ;;
        *)
            fail_usage "unknown argument: $1"
            ;;
    esac
done

(( seen_arch == 1 && seen_tool == 1 && seen_runtime == 1 && seen_output == 1 )) || \
    fail_usage "all four options are required"

case "$arch" in
    x86_64) appimage_arch=x86_64 ;;
    aarch64) appimage_arch=arm_aarch64 ;;
    *) fail_usage "unsupported architecture: $arch" ;;
esac

host_machine=$(uname -m)
case "$host_machine" in
    x86_64|amd64) native_arch=x86_64 ;;
    aarch64|arm64) native_arch=aarch64 ;;
    *)
        printf 'Error: unsupported native machine: %s\n' "$host_machine" >&2
        exit 1
        ;;
esac
if [[ $arch != "$native_arch" ]]; then
    printf 'Error: requested %s build on native %s host\n' "$arch" "$native_arch" >&2
    exit 1
fi

if [[ $appimagetool != /* ]]; then
    fail_usage "--appimagetool must be an absolute path"
fi
if [[ -L $appimagetool ]]; then
    fail_usage "appimagetool must not be a symlink"
fi
if [[ ! -f $appimagetool || ! -x $appimagetool ]]; then
    fail_usage "appimagetool must be a regular executable file"
fi

if [[ $runtime_file != /* ]]; then
    fail_usage "--runtime-file must be an absolute path"
fi
if [[ -L $runtime_file ]]; then
    fail_usage "runtime file must not be a symlink"
fi
if [[ ! -f $runtime_file || ! -r $runtime_file ]]; then
    fail_usage "runtime file must be a readable regular file"
fi
runtime_magic=$(od -An -t x1 -N4 -- "$runtime_file")
runtime_magic=${runtime_magic//[[:space:]]/}
[[ $runtime_magic == 7f454c46 ]] || fail_usage "runtime file must be ELF"
runtime_machine=$(od -An -t u2 -j18 -N2 -- "$runtime_file")
runtime_machine=${runtime_machine//[[:space:]]/}
case "$arch:$runtime_machine" in
    x86_64:62|aarch64:183) ;;
    *) fail_usage "runtime ELF architecture does not match --arch" ;;
esac

if [[ $output_dir != /* ]]; then
    fail_usage "--output-dir must be an absolute path"
fi
if [[ $output_dir == / || $output_dir == *//* || $output_dir == */./* || \
      $output_dir == */../* || $output_dir == */. || $output_dir == */.. ]]; then
    fail_usage "--output-dir is not a normalized safe path"
fi
output_dir=${output_dir%/}

script_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repository=$(CDPATH= cd -- "$script_dir/.." && pwd -P)
release_file="$repository/packaging/release.env"
checksum_file="$repository/packaging/appimage/appimagetool.sha256"
runtime_checksum_file="$repository/packaging/appimage/runtime.sha256"

read_release_value() {
    local wanted=$1
    local key value found=0 result=""
    while IFS='=' read -r key value; do
        if [[ $key == "$wanted" ]]; then
            (( found += 1 ))
            result=$value
        fi
    done < "$release_file"
    (( found == 1 )) || return 1
    printf '%s' "$result"
}

version=$(read_release_value VERSION) || {
    printf 'Error: release.env must contain exactly one VERSION\n' >&2
    exit 1
}
source_epoch=$(read_release_value SOURCE_DATE_EPOCH) || {
    printf 'Error: release.env must contain exactly one SOURCE_DATE_EPOCH\n' >&2
    exit 1
}
[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
    printf 'Error: invalid release VERSION\n' >&2
    exit 1
}
[[ $source_epoch =~ ^[1-9][0-9]*$ ]] || {
    printf 'Error: invalid SOURCE_DATE_EPOCH\n' >&2
    exit 1
}

ensure_output_directory() {
    local requested=$1
    local remainder=${requested#/}
    local current=/ component
    local -a components=()
    IFS='/' read -r -a components <<< "$remainder"
    for component in "${components[@]}"; do
        [[ -n $component ]] || fail_usage "empty output path component"
        if [[ $current == / ]]; then
            current="/$component"
        else
            current="$current/$component"
        fi
        if [[ -e $current || -L $current ]]; then
            [[ ! -L $current && -d $current ]] || \
                fail_usage "output path ancestry must contain only real directories"
        else
            mkdir -- "$current" || fail_usage "could not create output directory"
        fi
    done
}

ensure_output_directory "$output_dir"
[[ ! -L $output_dir && -d $output_dir ]] || \
    fail_usage "output directory must be a real directory"
[[ $(stat -Lc '%u' -- "$output_dir") == "$(id -u)" ]] || \
    fail_usage "output directory must be owned by the current user"
output_inode=$(stat -Lc '%d:%i' -- "$output_dir")

expected_checksum=""
checksum_matches=0
while read -r digest filename extra; do
    [[ -z ${digest:-} ]] && continue
    if [[ $filename == "appimagetool-$arch.AppImage" ]]; then
        [[ -z ${extra:-} && $digest =~ ^[0-9a-f]{64}$ ]] || {
            printf 'Error: malformed pinned appimagetool checksum\n' >&2
            exit 1
        }
        expected_checksum=$digest
        (( checksum_matches += 1 ))
    fi
done < "$checksum_file"
(( checksum_matches == 1 )) || {
    printf 'Error: expected one pinned appimagetool checksum for %s\n' "$arch" >&2
    exit 1
}
actual_checksum=$(sha256sum -- "$appimagetool")
actual_checksum=${actual_checksum%% *}
if [[ $actual_checksum != "$expected_checksum" ]]; then
    printf 'Error: appimagetool checksum does not match pinned %s digest\n' "$arch" >&2
    exit 1
fi

expected_runtime_checksum=""
runtime_checksum_matches=0
while read -r digest filename extra; do
    [[ -z ${digest:-} ]] && continue
    if [[ $filename == "runtime-$arch" ]]; then
        [[ -z ${extra:-} && $digest =~ ^[0-9a-f]{64}$ ]] || {
            printf 'Error: malformed pinned runtime checksum\n' >&2
            exit 1
        }
        expected_runtime_checksum=$digest
        (( runtime_checksum_matches += 1 ))
    fi
done < "$runtime_checksum_file"
(( runtime_checksum_matches == 1 )) || {
    printf 'Error: expected one pinned runtime checksum for %s\n' "$arch" >&2
    exit 1
}
actual_runtime_checksum=$(sha256sum -- "$runtime_file")
actual_runtime_checksum=${actual_runtime_checksum%% *}
if [[ $actual_runtime_checksum != "$expected_runtime_checksum" ]]; then
    printf 'Error: runtime checksum does not match pinned %s digest\n' "$arch" >&2
    exit 1
fi

temp_root=${TMPDIR:-/tmp}
[[ $temp_root == /* && ! -L $temp_root && -d $temp_root ]] || {
    printf 'Error: TMPDIR must be an absolute real directory\n' >&2
    exit 1
}
temp_root=$(CDPATH= cd -- "$temp_root" && pwd -P)

build_root=""
build_inode=""
output_temp=""
output_temp_inode=""

cleanup() {
    local status=$?
    trap - EXIT INT TERM HUP
    if [[ -n $output_temp && -f $output_temp && ! -L $output_temp ]]; then
        if [[ $(stat -Lc '%d:%i' -- "$output_temp") == "$output_temp_inode" ]]; then
            rm -f -- "$output_temp"
        fi
    fi
    if [[ -n $build_root && -d $build_root && ! -L $build_root ]]; then
        local leaf=${build_root#"$temp_root"/}
        if [[ $leaf != */* && $leaf == warp-control-appimage.* && \
              $(stat -Lc '%d:%i' -- "$build_root") == "$build_inode" ]]; then
            rm -rf -- "$build_root"
        fi
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

build_root=$(mktemp -d -- "$temp_root/warp-control-appimage.XXXXXXXX")
chmod 0700 "$build_root"
build_inode=$(stat -Lc '%d:%i' -- "$build_root")
appdir="$build_root/WARP-Control.AppDir"
pyinstaller_dist="$build_root/pyinstaller-dist"
pyinstaller_work="$build_root/pyinstaller-work"
extract_dir="$build_root/extracted"
mkdir -m 0700 -- "$appdir" "$pyinstaller_dist" "$pyinstaller_work" "$extract_dir"
appdir_inode=$(stat -Lc '%d:%i' -- "$appdir")

private_appimagetool="$build_root/appimagetool-$arch.AppImage"
install -m 0700 -- "$appimagetool" "$private_appimagetool"
[[ -f $private_appimagetool && -x $private_appimagetool && \
   ! -L $private_appimagetool ]] || {
    printf 'Error: could not create private appimagetool copy\n' >&2
    exit 1
}
private_checksum=$(sha256sum -- "$private_appimagetool")
private_checksum=${private_checksum%% *}
if [[ $private_checksum != "$expected_checksum" ]]; then
    printf 'Error: private appimagetool checksum changed while copying\n' >&2
    exit 1
fi
private_runtime="$build_root/runtime-$arch"
install -m 0600 -- "$runtime_file" "$private_runtime"
[[ -f $private_runtime && -r $private_runtime && ! -L $private_runtime ]] || {
    printf 'Error: could not create private runtime copy\n' >&2
    exit 1
}
private_runtime_checksum=$(sha256sum -- "$private_runtime")
private_runtime_checksum=${private_runtime_checksum%% *}
if [[ $private_runtime_checksum != "$expected_runtime_checksum" ]]; then
    printf 'Error: private runtime checksum changed while copying\n' >&2
    exit 1
fi

python_command=python3
verification_python=$(command -v python3)
if [[ -x $repository/.venv/bin/python ]]; then
    python_command="$repository/.venv/bin/python"
fi
"$python_command" -c 'import PyInstaller' 2>/dev/null || {
    printf 'Error: PyInstaller is required in the selected Python environment\n' >&2
    exit 1
}

export SOURCE_DATE_EPOCH=$source_epoch
export PYTHONHASHSEED=0
export PYINSTALLER_CONFIG_DIR="$build_root/pyinstaller-config"
mkdir -m 0700 -- "$PYINSTALLER_CONFIG_DIR"

"$python_command" -m PyInstaller \
    --noconfirm \
    --clean \
    --distpath "$pyinstaller_dist" \
    --workpath "$pyinstaller_work" \
    "$repository/packaging/appimage/warp-control.spec"

payload="$pyinstaller_dist/warp-control"
[[ -x $payload/warp-control && -d $payload/_internal ]] || {
    printf 'Error: PyInstaller did not create the expected onedir payload\n' >&2
    exit 1
}

for typelib in Gtk-3.0.typelib Gdk-3.0.typelib GLib-2.0.typelib \
               Gio-2.0.typelib AyatanaAppIndicator3-0.1.typelib; do
    find "$payload/_internal" -type f -name "$typelib" -print -quit | grep -q . || {
        printf 'Error: portable payload is missing GI typelib %s\n' "$typelib" >&2
        exit 1
    }
done
for library in 'libgtk-3.so*' 'libgdk-3.so*' 'libgobject-2.0.so*' \
               'libgio-2.0.so*' 'libgdk_pixbuf-2.0.so*' 'libcairo.so*' \
               'libayatana-appindicator3.so*'; do
    find "$payload/_internal" -type f -name "$library" -print -quit | grep -q . || {
        printf 'Error: portable payload is missing shared library %s\n' "$library" >&2
        exit 1
    }
done

[[ ! -L $appdir && $(stat -Lc '%d:%i' -- "$appdir") == "$appdir_inode" ]] || {
    printf 'Error: AppDir staging inode changed during build\n' >&2
    exit 1
}
mkdir -p -- \
    "$appdir/usr/bin" \
    "$appdir/usr/share/applications" \
    "$appdir/usr/share/icons/hicolor/scalable/apps" \
    "$appdir/usr/share/metainfo"
cp -a -- "$payload/." "$appdir/usr/bin/"
install -m 0755 -- "$repository/packaging/appimage/AppRun" "$appdir/AppRun"
install -m 0644 -- \
    "$repository/packaging/appimage/com.robler.warpcontrol.desktop" \
    "$appdir/com.robler.warpcontrol.desktop"
install -m 0644 -- \
    "$repository/packaging/appimage/com.robler.warpcontrol.desktop" \
    "$appdir/usr/share/applications/com.robler.warpcontrol.desktop"
install -m 0644 -- "$repository/data/icons/com.robler.warpcontrol.svg" \
    "$appdir/com.robler.warpcontrol.svg"
install -m 0644 -- "$repository/data/icons/com.robler.warpcontrol.svg" \
    "$appdir/.DirIcon"
install -m 0644 -- "$repository/data/icons/com.robler.warpcontrol.svg" \
    "$appdir/usr/share/icons/hicolor/scalable/apps/com.robler.warpcontrol.svg"
install -m 0644 -- "$repository/data/com.robler.warpcontrol.metainfo.xml" \
    "$appdir/usr/share/metainfo/com.robler.warpcontrol.metainfo.xml"

find "$appdir" -exec touch -h -d "@$source_epoch" -- {} +

candidate="$build_root/WARP-Control-$version-$arch.AppImage"
ARCH=$appimage_arch "$private_appimagetool" --appimage-extract-and-run --runtime-file "$private_runtime" "$appdir" "$candidate"
[[ -f $candidate && ! -L $candidate ]] || {
    printf 'Error: appimagetool did not create a regular image\n' >&2
    exit 1
}
chmod 0755 "$candidate"
touch -d "@$source_epoch" -- "$candidate"

(
    cd -- "$extract_dir"
    "$candidate" --appimage-extract >/dev/null
)
extracted="$extract_dir/squashfs-root"
[[ -d $extracted && ! -L $extracted ]] || {
    printf 'Error: final AppImage could not be inspected\n' >&2
    exit 1
}
"$verification_python" "$repository/packaging/appimage/verify_tree.py" \
    "$appdir" "$extracted"

for forbidden_path in \
    usr/libexec/warp-control \
    usr/share/polkit-1; do
    if [[ -e $extracted/$forbidden_path || -L $extracted/$forbidden_path ]]; then
        printf 'Error: forbidden AppImage path: %s\n' "$forbidden_path" >&2
        exit 1
    fi
done
for forbidden_name in warp-cli warp-svc dnf apt-get pacman; do
    while IFS= read -r -d '' bundled_path; do
        if [[ ${bundled_path##*/} == "$forbidden_name" ]]; then
            printf 'Error: forbidden executable in AppImage: %s\n' "$forbidden_name" >&2
            exit 1
        fi
        if [[ -L $bundled_path ]]; then
            link_target=$(readlink -- "$bundled_path")
            case "/$link_target/" in
                *"/$forbidden_name/"*)
                    printf 'Error: forbidden symlink target in AppImage: %s\n' \
                        "$forbidden_name" >&2
                    exit 1
                    ;;
            esac
        fi
    done < <(find "$extracted" -print0)
done

"$candidate" --appimage-extract-and-run --smoke-test

[[ ! -L $output_dir && $(stat -Lc '%d:%i' -- "$output_dir") == "$output_inode" ]] || {
    printf 'Error: output directory inode changed during build\n' >&2
    exit 1
}
output_temp=$(mktemp -- "$output_dir/.warp-control-appimage.XXXXXXXX")
output_temp_inode=$(stat -Lc '%d:%i' -- "$output_temp")
install -m 0755 -- "$candidate" "$output_temp"
final_output="$output_dir/WARP-Control-$version-$arch.AppImage"
if [[ -L $final_output ]]; then
    printf 'Error: refusing to replace a symlinked output image\n' >&2
    exit 1
fi
mv -fT -- "$output_temp" "$final_output"
output_temp=""
output_temp_inode=""

printf 'Built %s\n' "$final_output"
