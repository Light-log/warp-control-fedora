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
