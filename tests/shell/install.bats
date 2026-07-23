#!/usr/bin/env bats

setup() {
  export TEST_ROOT="$BATS_TEST_TMPDIR/root"
  mkdir -p "$TEST_ROOT"
  export WARP_CONTROL_OS_RELEASE="$TEST_ROOT/os-release"
  printf 'ID=ubuntu\nID_LIKE=debian\nPRETTY_NAME="Test Linux"\n' > "$WARP_CONTROL_OS_RELEASE"
  touch "$TEST_ROOT/warp-control_all.deb"
}

@test "dry-run detects Debian and prints the native command" {
  run bash scripts/install.sh --dry-run --package "$TEST_ROOT/warp-control_all.deb"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Familia detectada: debian"* ]]
  [[ "$output" == *"sudo apt-get install"* ]]
}

@test "Fedora rejects a Debian artifact" {
  printf 'ID=fedora\nPRETTY_NAME=Fedora\n' > "$WARP_CONTROL_OS_RELEASE"
  run bash scripts/install.sh --dry-run --package "$TEST_ROOT/warp-control_all.deb"
  [ "$status" -ne 0 ]
  [[ "$output" == *"paquete .rpm"* ]]
}

@test "confirmation happens before sudo" {
  printf 'ID=fedora\nPRETTY_NAME=Fedora\n' > "$WARP_CONTROL_OS_RELEASE"
  mv "$TEST_ROOT/warp-control_all.deb" "$TEST_ROOT/warp-control.rpm"
  mkdir "$TEST_ROOT/bin"
  cat > "$TEST_ROOT/bin/sudo" <<EOF
#!/usr/bin/env bash
touch "$TEST_ROOT/sudo-called"
EOF
  chmod +x "$TEST_ROOT/bin/sudo"
  PATH="$TEST_ROOT/bin:$PATH" run bash scripts/install.sh --package "$TEST_ROOT/warp-control.rpm"
  [ "$status" -ne 0 ]
  [ ! -e "$TEST_ROOT/sudo-called" ]
}

@test "artifact with a symlink ancestor is rejected" {
  printf 'ID=fedora\nPRETTY_NAME=Fedora\n' > "$WARP_CONTROL_OS_RELEASE"
  mkdir "$TEST_ROOT/real"
  touch "$TEST_ROOT/real/warp-control.rpm"
  ln -s "$TEST_ROOT/real" "$TEST_ROOT/link"
  run bash scripts/install.sh --dry-run --package "$TEST_ROOT/link/warp-control.rpm"
  [ "$status" -ne 0 ]
  [[ "$output" == *"ancestro"* ]]
}

make_minimal_appimage() {
  local target="$1" machine_lo="$2" machine_hi="${3:-00}"
  # ELF magic + 64-bit + little-endian, then a minimal e_machine field.
  printf '\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00' > "$target"
  printf '\x03\x00' >> "$target"
  printf "\\x$machine_lo\\x$machine_hi" >> "$target"
  printf '\x01\x00\x00\x00' >> "$target"
  head -c 64 /dev/zero >> "$target"
  chmod +x "$target"
}

@test "AppImage dry-run on an unknown distro never requests privilege" {
  printf 'ID=opensuse\nPRETTY_NAME=openSUSE\n' > "$WARP_CONTROL_OS_RELEASE"
  local host_machine
  host_machine=$(uname -m)
  local appimage="$TEST_ROOT/WARP-Control-2.0.0-${host_machine}.AppImage"
  if [ "$host_machine" = "aarch64" ]; then
    make_minimal_appimage "$appimage" b7
  else
    make_minimal_appimage "$appimage" 3e
  fi
  HOME="$TEST_ROOT/home" run bash scripts/install.sh --dry-run --package "$appimage"
  [ "$status" -eq 0 ]
  [[ "$output" == *".local/opt/warp-control"* ]]
  [[ "$output" != *"sudo"* ]]
}

@test "a shell script renamed to .AppImage is rejected" {
  printf 'ID=fedora\nPRETTY_NAME=Fedora\n' > "$WARP_CONTROL_OS_RELEASE"
  local fake="$TEST_ROOT/fake.AppImage"
  printf '#!/usr/bin/env bash\necho not an appimage\n' > "$fake"
  chmod +x "$fake"
  HOME="$TEST_ROOT/home" run bash scripts/install.sh --dry-run --package "$fake"
  [ "$status" -ne 0 ]
  [[ "$output" != *"sudo"* ]]
}
