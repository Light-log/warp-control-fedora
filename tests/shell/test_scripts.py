from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def run_script(script: str, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(ROOT / script), *args],
        cwd=ROOT,
        env={**os.environ, **env},
        text=True,
        capture_output=True,
        check=False,
    )


def os_release(tmp_path: Path, distro: str, like: str = "") -> Path:
    path = tmp_path / "os-release"
    path.write_text(f'ID="{distro}"\nID_LIKE="{like}"\nPRETTY_NAME="Test Linux"\n')
    return path


def test_install_dry_run_detects_debian_artifact_without_privilege(tmp_path: Path):
    release = os_release(tmp_path, "ubuntu", "debian")
    artifact = tmp_path / "warp-control_1.0_all.deb"
    artifact.write_text("fixture")
    result = run_script(
        "scripts/install.sh",
        "--dry-run",
        "--package",
        str(artifact),
        env={"WARP_CONTROL_OS_RELEASE": str(release)},
    )
    assert result.returncode == 0, result.stderr
    assert "Familia detectada: debian" in result.stdout
    assert str(artifact.resolve()) in result.stdout
    assert "sudo apt-get install" in result.stdout
    assert "Cloudflare WARP" in result.stdout


def test_install_rejects_wrong_artifact_for_family(tmp_path: Path):
    release = os_release(tmp_path, "fedora")
    artifact = tmp_path / "warp-control.deb"
    artifact.write_text("fixture")
    result = run_script(
        "scripts/install.sh",
        "--dry-run",
        "--package",
        str(artifact),
        env={"WARP_CONTROL_OS_RELEASE": str(release)},
    )
    assert result.returncode != 0
    assert "paquete .rpm" in result.stderr


def test_install_arch_only_prints_experimental_warp_instructions(tmp_path: Path):
    release = os_release(tmp_path, "arch")
    artifact = tmp_path / "warp-control-1.0-1-any.pkg.tar.zst"
    artifact.write_text("fixture")
    result = run_script(
        "scripts/install.sh",
        "--dry-run",
        "--package",
        str(artifact),
        env={"WARP_CONTROL_OS_RELEASE": str(release)},
    )
    assert result.returncode == 0
    assert "experimental" in result.stdout.lower()
    assert "AUR" in result.stdout
    assert "no instalará WARP automáticamente" in result.stdout


def test_install_requires_confirmation_before_invoking_privilege(tmp_path: Path):
    release = os_release(tmp_path, "fedora")
    artifact = tmp_path / "warp-control.rpm"
    artifact.write_text("fixture")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "sudo-called"
    sudo = fake_bin / "sudo"
    sudo.write_text(f"#!/usr/bin/env bash\nprintf called > {marker}\n")
    sudo.chmod(0o755)
    result = run_script(
        "scripts/install.sh",
        "--package",
        str(artifact),
        env={
            "WARP_CONTROL_OS_RELEASE": str(release),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
    )
    assert result.returncode != 0
    assert "confirmación" in result.stderr
    assert not marker.exists()


def test_bootstrap_contains_no_third_party_download_or_embedded_assets():
    script = (ROOT / "scripts/install.sh").read_text()
    assert "curl" not in script
    assert "pkg.cloudflareclient.com" not in script
    assert "<svg" not in script
    assert "python3 -" not in script


def test_install_rejects_test_os_release_symlink(tmp_path: Path):
    real_release = os_release(tmp_path, "fedora")
    linked_release = tmp_path / "linked-os-release"
    linked_release.symlink_to(real_release)
    artifact = tmp_path / "warp-control.rpm"
    artifact.write_text("fixture")
    result = run_script(
        "scripts/install.sh",
        "--dry-run",
        "--package",
        str(artifact),
        env={"WARP_CONTROL_OS_RELEASE": str(linked_release)},
    )
    assert result.returncode != 0
    assert "archivo regular" in result.stderr


def test_install_rejects_package_symlink(tmp_path: Path):
    release = os_release(tmp_path, "fedora")
    real_artifact = tmp_path / "real.rpm"
    real_artifact.write_text("fixture")
    linked_artifact = tmp_path / "warp-control.rpm"
    linked_artifact.symlink_to(real_artifact)
    result = run_script(
        "scripts/install.sh",
        "--dry-run",
        "--package",
        str(linked_artifact),
        env={"WARP_CONTROL_OS_RELEASE": str(release)},
    )
    assert result.returncode != 0
    assert "enlace simbólico" in result.stderr


def test_migration_defaults_to_dry_run_and_preserves_config(tmp_path: Path):
    home = tmp_path / "home"
    legacy = home / ".local/lib/warp-control"
    legacy.mkdir(parents=True)
    (legacy / "warp_control.py").write_text("old")
    config = home / ".config/warp-control/config.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"accent":"#123456"}')
    result = run_script("scripts/migrate-legacy.sh", env={"HOME": str(home)})
    assert result.returncode == 0, result.stderr
    assert "Vista previa" in result.stdout
    assert legacy.exists()
    assert config.read_text() == '{"accent":"#123456"}'


def test_migration_apply_moves_only_known_local_paths_to_backup(tmp_path: Path):
    home = tmp_path / "home"
    targets = [
        home / ".local/lib/warp-control",
        home / ".local/bin/warp-control",
        home / ".local/share/applications/warp-control.desktop",
    ]
    targets[0].mkdir(parents=True)
    (targets[0] / "warp_control.py").write_text("old")
    for target in targets[1:]:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("old")
    unrelated = home / ".local/bin/keep-me"
    unrelated.write_text("keep")
    config = home / ".config/warp-control/config.json"
    config.parent.mkdir(parents=True)
    config.write_text("keep config")
    result = run_script(
        "scripts/migrate-legacy.sh",
        "--apply",
        "--yes",
        env={"HOME": str(home), "WARP_CONTROL_TIMESTAMP": "test-run"},
    )
    assert result.returncode == 0, result.stderr
    assert all(not target.exists() for target in targets)
    backup = home / ".local/state/warp-control/legacy-backups/test-run"
    assert (backup / "lib/warp-control/warp_control.py").read_text() == "old"
    assert (backup / "bin/warp-control").read_text() == "old"
    assert (backup / "share/applications/warp-control.desktop").read_text() == "old"
    assert unrelated.read_text() == "keep"
    assert config.read_text() == "keep config"


def test_migration_fails_closed_on_legacy_symlink(tmp_path: Path):
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    outside.mkdir()
    target = home / ".local/lib/warp-control"
    target.parent.mkdir(parents=True)
    target.symlink_to(outside, target_is_directory=True)
    result = run_script(
        "scripts/migrate-legacy.sh", "--apply", "--yes", env={"HOME": str(home)}
    )
    assert result.returncode != 0
    assert "enlace simbólico" in result.stderr
    assert outside.exists()


def test_migration_fails_closed_on_backup_ancestor_symlink(tmp_path: Path):
    home = tmp_path / "home"
    legacy = home / ".local/lib/warp-control"
    legacy.mkdir(parents=True)
    (legacy / "warp_control.py").write_text("old")
    outside = tmp_path / "outside"
    outside.mkdir()
    state = home / ".local/state"
    state.symlink_to(outside, target_is_directory=True)
    result = run_script(
        "scripts/migrate-legacy.sh", "--apply", "--yes", env={"HOME": str(home)}
    )
    assert result.returncode != 0
    assert "enlace simbólico" in result.stderr
    assert legacy.exists()
    assert not any(outside.iterdir())


def test_migration_rolls_back_if_a_move_fails(tmp_path: Path):
    home = tmp_path / "home"
    legacy_dir = home / ".local/lib/warp-control"
    legacy_bin = home / ".local/bin/warp-control"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "warp_control.py").write_text("old")
    legacy_bin.parent.mkdir(parents=True)
    legacy_bin.write_text("old")
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    counter = tmp_path / "mv-count"
    fake_mv = fake_bin / "mv"
    fake_mv.write_text(
        "#!/usr/bin/env bash\n"
        f"n=$(cat {counter} 2>/dev/null || printf 0)\n"
        "n=$((n + 1))\n"
        f"printf %s \"$n\" > {counter}\n"
        "if [ \"$n\" -eq 2 ]; then exit 9; fi\n"
        "exec /usr/bin/mv \"$@\"\n"
    )
    fake_mv.chmod(0o755)
    result = run_script(
        "scripts/migrate-legacy.sh",
        "--apply",
        "--yes",
        env={
            "HOME": str(home),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "WARP_CONTROL_TIMESTAMP": "rollback",
        },
    )
    assert result.returncode != 0
    assert "revirtieron" in result.stderr
    assert (legacy_dir / "warp_control.py").read_text() == "old"
    assert legacy_bin.read_text() == "old"


def test_legacy_wrapper_contains_no_embedded_application():
    wrapper = (ROOT / "instalar-warp-control-fedora.sh").read_text()
    assert "scripts/install.sh" in wrapper
    assert "__WARP_CONTROL_PYTHON__" not in wrapper
    assert len(wrapper.splitlines()) < 30
