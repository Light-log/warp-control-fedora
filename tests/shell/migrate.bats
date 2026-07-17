#!/usr/bin/env bats

setup() {
  export HOME="$BATS_TEST_TMPDIR/home"
  mkdir -p "$HOME/.local/lib/warp-control" "$HOME/.config/warp-control"
  printf old > "$HOME/.local/lib/warp-control/warp_control.py"
  printf config > "$HOME/.config/warp-control/config.json"
}

@test "migration is a dry-run by default" {
  run bash scripts/migrate-legacy.sh
  [ "$status" -eq 0 ]
  [ -e "$HOME/.local/lib/warp-control/warp_control.py" ]
  [ "$(cat "$HOME/.config/warp-control/config.json")" = config ]
}

@test "apply creates a recoverable backup and preserves config" {
  export WARP_CONTROL_TIMESTAMP=bats
  run bash scripts/migrate-legacy.sh --apply --yes
  [ "$status" -eq 0 ]
  [ -e "$HOME/.local/state/warp-control/legacy-backups/bats/lib/warp-control/warp_control.py" ]
  [ "$(cat "$HOME/.config/warp-control/config.json")" = config ]
}
