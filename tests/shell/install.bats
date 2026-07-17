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
