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

@test "a symlinked legacy target fails closed" {
  rm -r "$HOME/.local/lib/warp-control"
  mkdir "$BATS_TEST_TMPDIR/outside"
  ln -s "$BATS_TEST_TMPDIR/outside" "$HOME/.local/lib/warp-control"
  run bash scripts/migrate-legacy.sh --apply --yes
  [ "$status" -ne 0 ]
  [[ "$output" == *"enlace simbólico"* ]]
}

@test "a failed second move rolls the first one back" {
  mkdir -p "$HOME/.local/bin" "$BATS_TEST_TMPDIR/bin"
  printf old > "$HOME/.local/bin/warp-control"
  cat > "$BATS_TEST_TMPDIR/bin/mv" <<EOF
#!/usr/bin/env bash
n=\$(cat "$BATS_TEST_TMPDIR/count" 2>/dev/null || printf 0)
n=\$((n + 1))
printf %s "\$n" > "$BATS_TEST_TMPDIR/count"
[ "\$n" -eq 2 ] && exit 9
exec /usr/bin/mv "\$@"
EOF
  chmod +x "$BATS_TEST_TMPDIR/bin/mv"
  PATH="$BATS_TEST_TMPDIR/bin:$PATH" run bash scripts/migrate-legacy.sh --apply --yes
  [ "$status" -ne 0 ]
  [ -e "$HOME/.local/lib/warp-control/warp_control.py" ]
  [ -e "$HOME/.local/bin/warp-control" ]
}

@test "current packaged autostart is preserved" {
  rm -r "$HOME/.local/lib/warp-control"
  mkdir -p "$HOME/.config/autostart"
  printf '[Desktop Entry]\nExec=/usr/bin/warp-control --background\n' > "$HOME/.config/autostart/warp-control.desktop"
  run bash scripts/migrate-legacy.sh --apply --yes
  [ "$status" -eq 0 ]
  grep -q '^Exec=/usr/bin/warp-control --background$' "$HOME/.config/autostart/warp-control.desktop"
}
