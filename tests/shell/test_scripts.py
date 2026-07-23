from __future__ import annotations

import os
import platform
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
HOST_MACHINE = platform.machine()
REAL_APPIMAGE = ROOT / "dist/WARP-Control-2.0.0-x86_64.AppImage"

ELF_MACHINE = {"x86_64": (0x3E).to_bytes(2, "little"), "aarch64": (0xB7).to_bytes(2, "little")}
OTHER_ARCH_FOR = {"x86_64": "aarch64", "aarch64": "x86_64"}


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


def minimal_elf_appimage(path: Path, arch: str = "x86_64", *, executable: bool = True) -> Path:
    """Write a minimal ELF header sufficient for magic/class/machine checks.

    This is not a real AppImage payload; it only exercises install.sh's
    format-detection contract (ELF magic, 64-bit class, little-endian data,
    e_machine), not extraction.
    """
    e_ident = bytes([0x7F, 0x45, 0x4C, 0x46, 2, 1, 1, 0]) + bytes(8)
    e_type = (3).to_bytes(2, "little")
    e_machine = ELF_MACHINE[arch]
    e_version = (1).to_bytes(4, "little")
    header = e_ident + e_type + e_machine + e_version
    path.write_bytes(header + bytes(64 - len(header)))
    if executable:
        path.chmod(0o755)
    return path


def fake_command(directory: Path, name: str, marker: Path) -> None:
    script = directory / name
    script.write_text(f"#!/usr/bin/env bash\nprintf called > {marker}\n")
    script.chmod(0o755)


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


def test_install_rejects_package_with_symlink_ancestor(tmp_path: Path):
    release = os_release(tmp_path, "fedora")
    real_dir = tmp_path / "real-artifacts"
    real_dir.mkdir()
    artifact = real_dir / "warp-control.rpm"
    artifact.write_text("fixture")
    linked_dir = tmp_path / "artifacts"
    linked_dir.symlink_to(real_dir, target_is_directory=True)
    result = run_script(
        "scripts/install.sh",
        "--dry-run",
        "--package",
        str(linked_dir / artifact.name),
        env={"WARP_CONTROL_OS_RELEASE": str(release)},
    )
    assert result.returncode != 0
    assert "ancestro" in result.stderr


def test_install_rejects_symlinked_runtime_directory(tmp_path: Path):
    release = os_release(tmp_path, "fedora")
    artifact = tmp_path / "warp-control.rpm"
    artifact.write_text("fixture")
    real_runtime = tmp_path / "real-runtime"
    real_runtime.mkdir(mode=0o700)
    linked_runtime = tmp_path / "runtime"
    linked_runtime.symlink_to(real_runtime, target_is_directory=True)
    result = run_script(
        "scripts/install.sh",
        "--dry-run",
        "--package",
        str(artifact),
        env={
            "WARP_CONTROL_OS_RELEASE": str(release),
            "XDG_RUNTIME_DIR": str(linked_runtime),
        },
    )
    assert result.returncode != 0
    assert "temporal" in result.stderr.lower()


def test_install_rejects_user_temp_directory_writable_by_others(tmp_path: Path):
    release = os_release(tmp_path, "fedora")
    artifact = tmp_path / "warp-control.rpm"
    artifact.write_text("fixture")
    unsafe_temp = tmp_path / "unsafe-temp"
    unsafe_temp.mkdir(mode=0o777)
    unsafe_temp.chmod(0o777)
    result = run_script(
        "scripts/install.sh",
        "--dry-run",
        "--package",
        str(artifact),
        env={
            "WARP_CONTROL_OS_RELEASE": str(release),
            "XDG_RUNTIME_DIR": "",
            "TMPDIR": str(unsafe_temp),
        },
    )
    assert result.returncode != 0
    assert "escritura a terceros" in result.stderr


def test_install_uses_private_snapshot_if_original_changes(tmp_path: Path):
    release = os_release(tmp_path, "fedora")
    artifact = tmp_path / "warp-control.rpm"
    artifact.write_text("approved-content")
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    installed_content = tmp_path / "installed-content"
    staged_path = tmp_path / "staged-path"
    sudo = fake_bin / "sudo"
    sudo.write_text(
        "#!/usr/bin/env bash\n"
        f"printf changed-after-plan > {artifact}\n"
        "for last; do :; done\n"
        f"cat -- \"$last\" > {installed_content}\n"
        f"printf %s \"$last\" > {staged_path}\n"
    )
    sudo.chmod(0o755)
    result = run_script(
        "scripts/install.sh",
        "--yes",
        "--package",
        str(artifact),
        env={
            "WARP_CONTROL_OS_RELEASE": str(release),
            "XDG_RUNTIME_DIR": str(runtime),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
    )
    assert result.returncode == 0, result.stderr
    assert installed_content.read_text() == "approved-content"
    snapshot = Path(staged_path.read_text())
    assert snapshot.parent.parent == runtime
    assert not snapshot.exists()
    assert "SHA-256" in result.stdout


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


def test_migration_moves_only_identified_legacy_autostart(tmp_path: Path):
    home = tmp_path / "home"
    legacy_autostart = home / ".config/autostart/warp-control.desktop"
    legacy_autostart.parent.mkdir(parents=True)
    legacy_autostart.write_text(
        "[Desktop Entry]\n"
        f"Exec={home}/.local/bin/warp-control\n"
        "X-GNOME-Autostart-enabled=true\n"
    )
    config = home / ".config/warp-control/config.json"
    config.parent.mkdir(parents=True)
    config.write_text("keep config")
    preview = run_script("scripts/migrate-legacy.sh", env={"HOME": str(home)})
    assert preview.returncode == 0, preview.stderr
    assert str(legacy_autostart) in preview.stdout
    assert legacy_autostart.exists()

    applied = run_script(
        "scripts/migrate-legacy.sh",
        "--apply",
        "--yes",
        env={"HOME": str(home), "WARP_CONTROL_TIMESTAMP": "autostart"},
    )
    assert applied.returncode == 0, applied.stderr
    backup = home / ".local/state/warp-control/legacy-backups/autostart"
    moved = backup / "config/autostart/warp-control.desktop"
    assert "Exec=" + str(home / ".local/bin/warp-control") in moved.read_text()
    assert not legacy_autostart.exists()
    assert config.read_text() == "keep config"


def test_migration_preserves_current_packaged_autostart(tmp_path: Path):
    home = tmp_path / "home"
    autostart = home / ".config/autostart/warp-control.desktop"
    autostart.parent.mkdir(parents=True)
    content = "[Desktop Entry]\nExec=/usr/bin/warp-control --background\n"
    autostart.write_text(content)
    result = run_script(
        "scripts/migrate-legacy.sh",
        "--apply",
        "--yes",
        env={"HOME": str(home), "WARP_CONTROL_TIMESTAMP": "current"},
    )
    assert result.returncode == 0, result.stderr
    assert autostart.read_text() == content
    assert "No se encontraron" in result.stdout


def test_migration_rolls_back_legacy_autostart_move(tmp_path: Path):
    home = tmp_path / "home"
    legacy_dir = home / ".local/lib/warp-control"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "warp_control.py").write_text("old")
    autostart = home / ".config/autostart/warp-control.desktop"
    autostart.parent.mkdir(parents=True)
    autostart.write_text(f"[Desktop Entry]\nExec={home}/.local/bin/warp-control\n")
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
            "WARP_CONTROL_TIMESTAMP": "autostart-rollback",
        },
    )
    assert result.returncode != 0
    assert (legacy_dir / "warp_control.py").read_text() == "old"
    assert autostart.exists()


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


# --- Task 4: unprivileged AppImage installation ------------------------


def test_appimage_dry_run_is_unprivileged_on_unknown_linux(tmp_path: Path):
    appimage = minimal_elf_appimage(tmp_path / "WARP-Control-2.0.0-x86_64.AppImage", HOST_MACHINE)
    result = run_script(
        "scripts/install.sh",
        "--dry-run",
        "--package",
        str(appimage),
        env={
            "WARP_CONTROL_OS_RELEASE": str(os_release(tmp_path, "opensuse")),
            "HOME": str(tmp_path / "home"),
        },
    )
    assert result.returncode == 0, result.stderr
    assert ".local/opt/warp-control" in result.stdout
    assert "sudo" not in result.stdout


def test_appimage_format_is_detected_before_distro_family_selection(tmp_path: Path):
    appimage = minimal_elf_appimage(tmp_path / "warp-control.AppImage", HOST_MACHINE)
    for distro in ("fedora", "ubuntu", "arch"):
        result = run_script(
            "scripts/install.sh",
            "--dry-run",
            "--package",
            str(appimage),
            env={
                "WARP_CONTROL_OS_RELEASE": str(os_release(tmp_path, distro)),
                "HOME": str(tmp_path / f"home-{distro}"),
            },
        )
        assert result.returncode == 0, f"{distro}: {result.stderr}"
        assert "sudo" not in result.stdout
        assert "Distribución no soportada" not in result.stderr


def test_appimage_dry_run_accepts_matching_host_architecture(tmp_path: Path):
    appimage = minimal_elf_appimage(tmp_path / f"WARP-Control-2.0.0-{HOST_MACHINE}.AppImage", HOST_MACHINE)
    result = run_script(
        "scripts/install.sh",
        "--dry-run",
        "--package",
        str(appimage),
        env={
            "WARP_CONTROL_OS_RELEASE": str(os_release(tmp_path, "fedora")),
            "HOME": str(tmp_path / "home"),
        },
    )
    assert result.returncode == 0, result.stderr


def test_appimage_rejects_architecture_mismatch_with_host(tmp_path: Path):
    other_arch = OTHER_ARCH_FOR[HOST_MACHINE]
    appimage = minimal_elf_appimage(tmp_path / f"WARP-Control-2.0.0-{other_arch}.AppImage", other_arch)
    result = run_script(
        "scripts/install.sh",
        "--dry-run",
        "--package",
        str(appimage),
        env={
            "WARP_CONTROL_OS_RELEASE": str(os_release(tmp_path, "fedora")),
            "HOME": str(tmp_path / "home"),
        },
    )
    assert result.returncode != 0
    assert "sudo" not in result.stdout


def test_appimage_rejects_a_shell_script_with_appimage_extension(tmp_path: Path):
    fake = tmp_path / "not-really-an.AppImage"
    fake.write_text("#!/usr/bin/env bash\nprintf 'not an appimage\\n'\n")
    fake.chmod(0o755)
    result = run_script(
        "scripts/install.sh",
        "--dry-run",
        "--package",
        str(fake),
        env={
            "WARP_CONTROL_OS_RELEASE": str(os_release(tmp_path, "fedora")),
            "HOME": str(tmp_path / "home"),
        },
    )
    assert result.returncode != 0
    assert "sudo" not in result.stdout


def test_appimage_rejects_group_or_world_writable_source(tmp_path: Path):
    appimage = minimal_elf_appimage(tmp_path / f"WARP-Control-2.0.0-{HOST_MACHINE}.AppImage", HOST_MACHINE)
    appimage.chmod(0o777)
    result = run_script(
        "scripts/install.sh",
        "--dry-run",
        "--package",
        str(appimage),
        env={
            "WARP_CONTROL_OS_RELEASE": str(os_release(tmp_path, "fedora")),
            "HOME": str(tmp_path / "home"),
        },
    )
    assert result.returncode != 0
    assert "escritura de grupo o terceros" in result.stderr


def test_appimage_dry_run_never_names_a_package_manager(tmp_path: Path):
    appimage = minimal_elf_appimage(tmp_path / f"WARP-Control-2.0.0-{HOST_MACHINE}.AppImage", HOST_MACHINE)
    result = run_script(
        "scripts/install.sh",
        "--dry-run",
        "--package",
        str(appimage),
        env={
            "WARP_CONTROL_OS_RELEASE": str(os_release(tmp_path, "fedora")),
            "HOME": str(tmp_path / "home"),
        },
    )
    assert result.returncode == 0, result.stderr
    for manager in ("dnf", "apt-get", "pacman"):
        assert manager not in result.stdout


def test_appimage_install_never_invokes_sudo(tmp_path: Path):
    # A minimal ELF fixture is sufficient for dry-run format detection, but a
    # real install must execute AppImage extraction.
    if not REAL_APPIMAGE.is_file() or HOST_MACHINE != "x86_64":
        pytest.skip("requires a built host AppImage artifact")
    appimage = REAL_APPIMAGE
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "sudo-called"
    fake_command(fake_bin, "sudo", marker)
    for manager in ("dnf", "apt-get", "pacman"):
        fake_command(fake_bin, manager, tmp_path / f"{manager}-called")
    result = run_script(
        "scripts/install.sh",
        "--yes",
        "--package",
        str(appimage),
        env={
            "WARP_CONTROL_OS_RELEASE": str(os_release(tmp_path, "fedora")),
            "HOME": str(tmp_path / "home"),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
    )
    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    for manager in ("dnf", "apt-get", "pacman"):
        assert not (tmp_path / f"{manager}-called").exists()


def test_appimage_install_root_override_must_be_absolute(tmp_path: Path):
    appimage = minimal_elf_appimage(tmp_path / f"WARP-Control-2.0.0-{HOST_MACHINE}.AppImage", HOST_MACHINE)
    result = run_script(
        "scripts/install.sh",
        "--dry-run",
        "--package",
        str(appimage),
        env={
            "WARP_CONTROL_OS_RELEASE": str(os_release(tmp_path, "fedora")),
            "HOME": str(tmp_path / "home"),
            "WARP_CONTROL_INSTALL_ROOT": "relative/install/root",
        },
    )
    assert result.returncode != 0
    assert "absolut" in result.stderr.lower()


def test_appimage_install_root_override_is_honored(tmp_path: Path):
    appimage = minimal_elf_appimage(tmp_path / f"WARP-Control-2.0.0-{HOST_MACHINE}.AppImage", HOST_MACHINE)
    install_root = tmp_path / "custom-root"
    result = run_script(
        "scripts/install.sh",
        "--dry-run",
        "--package",
        str(appimage),
        env={
            "WARP_CONTROL_OS_RELEASE": str(os_release(tmp_path, "fedora")),
            "HOME": str(tmp_path / "home"),
            "WARP_CONTROL_INSTALL_ROOT": str(install_root),
        },
    )
    assert result.returncode == 0, result.stderr
    assert str(install_root / "opt/warp-control") in result.stdout


def test_appimage_package_rejects_symlink_ancestor(tmp_path: Path):
    real_dir = tmp_path / "real-artifacts"
    real_dir.mkdir()
    appimage = minimal_elf_appimage(real_dir / f"WARP-Control-2.0.0-{HOST_MACHINE}.AppImage", HOST_MACHINE)
    linked_dir = tmp_path / "artifacts"
    linked_dir.symlink_to(real_dir, target_is_directory=True)
    result = run_script(
        "scripts/install.sh",
        "--dry-run",
        "--package",
        str(linked_dir / appimage.name),
        env={
            "WARP_CONTROL_OS_RELEASE": str(os_release(tmp_path, "fedora")),
            "HOME": str(tmp_path / "home"),
        },
    )
    assert result.returncode != 0
    assert "ancestro" in result.stderr


def test_appimage_package_rejects_direct_symlink(tmp_path: Path):
    real = minimal_elf_appimage(tmp_path / "real.AppImage", HOST_MACHINE)
    linked = tmp_path / f"WARP-Control-2.0.0-{HOST_MACHINE}.AppImage"
    linked.symlink_to(real)
    result = run_script(
        "scripts/install.sh",
        "--dry-run",
        "--package",
        str(linked),
        env={
            "WARP_CONTROL_OS_RELEASE": str(os_release(tmp_path, "fedora")),
            "HOME": str(tmp_path / "home"),
        },
    )
    assert result.returncode != 0
    assert "enlace simbólico" in result.stderr


REAL_APPIMAGE_REASON = "requires a built dist/WARP-Control-2.0.0-x86_64.AppImage artifact"
requires_real_appimage = pytest.mark.skipif(
    not REAL_APPIMAGE.is_file() or HOST_MACHINE != "x86_64",
    reason=REAL_APPIMAGE_REASON,
)


@requires_real_appimage
def test_appimage_install_creates_the_exact_local_layout(tmp_path: Path):
    home = tmp_path / "home"
    result = run_script(
        "scripts/install.sh",
        "--yes",
        "--package",
        str(REAL_APPIMAGE),
        env={
            "WARP_CONTROL_OS_RELEASE": str(os_release(tmp_path, "fedora")),
            "HOME": str(home),
        },
    )
    assert result.returncode == 0, result.stderr
    installed_image = home / ".local/opt/warp-control/WARP-Control-2.0.0-x86_64.AppImage"
    launcher = home / ".local/bin/warp-control"
    desktop = home / ".local/share/applications/com.devruby.warpcontrol.desktop"
    icon = home / ".local/share/icons/hicolor/scalable/apps/com.devruby.warpcontrol.svg"
    assert installed_image.is_file()
    assert not installed_image.is_symlink()
    assert os.access(installed_image, os.X_OK)
    assert launcher.is_file()
    assert desktop.is_file()
    assert icon.is_file()


@requires_real_appimage
def test_appimage_install_rewrites_desktop_exec_to_local_launcher(tmp_path: Path):
    home = tmp_path / "home"
    result = run_script(
        "scripts/install.sh",
        "--yes",
        "--package",
        str(REAL_APPIMAGE),
        env={
            "WARP_CONTROL_OS_RELEASE": str(os_release(tmp_path, "fedora")),
            "HOME": str(home),
        },
    )
    assert result.returncode == 0, result.stderr
    desktop = home / ".local/share/applications/com.devruby.warpcontrol.desktop"
    launcher = home / ".local/bin/warp-control"
    text = desktop.read_text(encoding="utf-8")
    assert f"Exec={launcher}" in text
    assert "Exec=warp-control\n" not in text


@requires_real_appimage
def test_appimage_install_does_not_replace_a_foreign_launcher(tmp_path: Path):
    home = tmp_path / "home"
    launcher = home / ".local/bin/warp-control"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/usr/bin/env bash\nexec /opt/other-vendor/warp-control \"$@\"\n")
    launcher.chmod(0o755)
    original_content = launcher.read_text()
    result = run_script(
        "scripts/install.sh",
        "--yes",
        "--package",
        str(REAL_APPIMAGE),
        env={
            "WARP_CONTROL_OS_RELEASE": str(os_release(tmp_path, "fedora")),
            "HOME": str(home),
        },
    )
    assert result.returncode != 0
    assert launcher.read_text() == original_content


@requires_real_appimage
def test_appimage_install_rejects_opt_path_mentioned_only_in_foreign_launcher_comment(tmp_path: Path):
    home = tmp_path / "home"
    opt_dir = home / ".local/opt/warp-control"
    launcher = home / ".local/bin/warp-control"
    launcher.parent.mkdir(parents=True)
    launcher.write_text(
        "#!/usr/bin/env bash\n"
        f"# old files may exist under {opt_dir}/\n"
        "exec /opt/other-vendor/warp-control \"$@\"\n"
    )
    launcher.chmod(0o755)
    original_content = launcher.read_text()
    result = run_script(
        "scripts/install.sh",
        "--yes",
        "--package",
        str(REAL_APPIMAGE),
        env={
            "WARP_CONTROL_OS_RELEASE": str(os_release(tmp_path, "fedora")),
            "HOME": str(home),
        },
    )
    assert result.returncode != 0
    assert launcher.read_text() == original_content


@requires_real_appimage
def test_appimage_install_replaces_its_own_prior_launcher(tmp_path: Path):
    home = tmp_path / "home"
    opt_dir = home / ".local/opt/warp-control"
    opt_dir.mkdir(parents=True)
    launcher = home / ".local/bin/warp-control"
    launcher.parent.mkdir(parents=True)
    launcher.write_text(
        f"#!/usr/bin/env bash\nexec {opt_dir}/WARP-Control-1.9.0-x86_64.AppImage \"$@\"\n"
    )
    launcher.chmod(0o755)
    result = run_script(
        "scripts/install.sh",
        "--yes",
        "--package",
        str(REAL_APPIMAGE),
        env={
            "WARP_CONTROL_OS_RELEASE": str(os_release(tmp_path, "fedora")),
            "HOME": str(home),
        },
    )
    assert result.returncode == 0, result.stderr
    installed_image = opt_dir / "WARP-Control-2.0.0-x86_64.AppImage"
    assert str(installed_image) in launcher.read_text()


@requires_real_appimage
def test_appimage_install_rolls_back_atomically_on_failed_replacement(tmp_path: Path):
    home = tmp_path / "home"
    opt_dir = home / ".local/opt/warp-control"
    opt_dir.mkdir(parents=True)
    installed_image = opt_dir / "WARP-Control-2.0.0-x86_64.AppImage"
    installed_image.write_bytes(b"previous image bytes\n")
    installed_image.chmod(0o755)
    launcher = home / ".local/bin/warp-control"
    launcher.parent.mkdir(parents=True)
    launcher_content = f"#!/usr/bin/env bash\nexec {installed_image} \"$@\"\n"
    launcher.write_text(launcher_content)
    launcher.chmod(0o755)
    desktop = home / ".local/share/applications/com.devruby.warpcontrol.desktop"
    desktop.parent.mkdir(parents=True)
    desktop_content = "[Desktop Entry]\nName=Previous WARP Control\nExec=/previous\n"
    desktop.write_text(desktop_content)
    icon = home / ".local/share/icons/hicolor/scalable/apps/com.devruby.warpcontrol.svg"
    icon.parent.mkdir(parents=True)
    icon_content = "<svg><!-- previous icon --></svg>\n"
    icon.write_text(icon_content)

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    counter = tmp_path / "mv-count"
    fake_mv = fake_bin / "mv"
    fake_mv.write_text(
        "#!/usr/bin/env bash\n"
        f"n=$(cat {counter} 2>/dev/null || printf 0)\n"
        "n=$((n + 1))\n"
        f"printf %s \"$n\" > {counter}\n"
        "if [ \"$n\" -eq 4 ]; then exit 9; fi\n"
        "exec /usr/bin/mv \"$@\"\n"
    )
    fake_mv.chmod(0o755)
    result = run_script(
        "scripts/install.sh",
        "--yes",
        "--package",
        str(REAL_APPIMAGE),
        env={
            "WARP_CONTROL_OS_RELEASE": str(os_release(tmp_path, "fedora")),
            "HOME": str(home),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
    )
    assert result.returncode != 0
    assert installed_image.read_bytes() == b"previous image bytes\n"
    assert launcher.read_text() == launcher_content
    assert desktop.read_text() == desktop_content
    assert icon.read_text() == icon_content
    assert not list(home.rglob(".warp-control.*"))


@requires_real_appimage
def test_appimage_incomplete_rollback_retains_recovery_backups(tmp_path: Path):
    home = tmp_path / "home"
    opt_dir = home / ".local/opt/warp-control"
    opt_dir.mkdir(parents=True)
    installed_image = opt_dir / "WARP-Control-2.0.0-x86_64.AppImage"
    installed_image.write_bytes(b"recoverable previous image\n")
    installed_image.chmod(0o755)
    launcher = home / ".local/bin/warp-control"
    launcher.parent.mkdir(parents=True)
    launcher_content = f"#!/usr/bin/env bash\nexec {installed_image} \"$@\"\n"
    launcher.write_text(launcher_content)
    launcher.chmod(0o755)
    desktop = home / ".local/share/applications/com.devruby.warpcontrol.desktop"
    desktop.parent.mkdir(parents=True)
    desktop_content = "[Desktop Entry]\nName=Recoverable previous desktop\nExec=/previous\n"
    desktop.write_text(desktop_content)
    icon = home / ".local/share/icons/hicolor/scalable/apps/com.devruby.warpcontrol.svg"
    icon.parent.mkdir(parents=True)
    icon.write_text("<svg><!-- recoverable previous icon --></svg>\n")

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    counter = tmp_path / "mv-count"
    fake_mv = fake_bin / "mv"
    fake_mv.write_text(
        "#!/usr/bin/env bash\n"
        f"n=$(cat {counter} 2>/dev/null || printf 0)\n"
        "n=$((n + 1))\n"
        f"printf %s \"$n\" > {counter}\n"
        "if [ \"$n\" -eq 4 ] || [ \"$n\" -eq 5 ]; then exit 9; fi\n"
        "exec /usr/bin/mv \"$@\"\n"
    )
    fake_mv.chmod(0o755)
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    result = run_script(
        "scripts/install.sh",
        "--yes",
        "--package",
        str(REAL_APPIMAGE),
        env={
            "WARP_CONTROL_OS_RELEASE": str(os_release(tmp_path, "fedora")),
            "HOME": str(home),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "TMPDIR": str(runtime),
        },
    )
    assert result.returncode != 0
    assert "restauración quedó incompleta" in result.stderr
    assert "se restauró la instalación anterior" not in result.stderr
    match = re.search(r"Copias de recuperación: (.+)$", result.stderr, re.MULTILINE)
    assert match is not None
    recovery = Path(match.group(1))
    assert recovery.parent == runtime
    assert recovery.is_dir()
    assert (recovery / "backup-image").read_bytes() == b"recoverable previous image\n"
    assert (recovery / "backup-launcher").read_text() == launcher_content
    assert (recovery / "backup-desktop").read_text() == desktop_content


@requires_real_appimage
def test_appimage_rollback_rm_failure_retains_recovery_backups(tmp_path: Path):
    home = tmp_path / "home"
    opt_dir = home / ".local/opt/warp-control"
    opt_dir.mkdir(parents=True)
    installed_image = opt_dir / "WARP-Control-2.0.0-x86_64.AppImage"
    installed_image.write_bytes(b"previous image for rm recovery\n")
    installed_image.chmod(0o755)
    launcher = home / ".local/bin/warp-control"

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    counter = tmp_path / "mv-count"
    fake_mv = fake_bin / "mv"
    fake_mv.write_text(
        "#!/usr/bin/env bash\n"
        f"n=$(cat {counter} 2>/dev/null || printf 0)\n"
        "n=$((n + 1))\n"
        f"printf %s \"$n\" > {counter}\n"
        "if [ \"$n\" -eq 3 ]; then exit 9; fi\n"
        "exec /usr/bin/mv \"$@\"\n"
    )
    fake_mv.chmod(0o755)
    fake_rm = fake_bin / "rm"
    fake_rm.write_text(
        "#!/usr/bin/env bash\n"
        "last=${!#}\n"
        f"if [ \"$last\" = \"{launcher}\" ]; then exit 8; fi\n"
        "exec /usr/bin/rm \"$@\"\n"
    )
    fake_rm.chmod(0o755)
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    result = run_script(
        "scripts/install.sh",
        "--yes",
        "--package",
        str(REAL_APPIMAGE),
        env={
            "WARP_CONTROL_OS_RELEASE": str(os_release(tmp_path, "fedora")),
            "HOME": str(home),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "TMPDIR": str(runtime),
        },
    )
    assert result.returncode != 0
    assert "restauración quedó incompleta" in result.stderr
    assert "se restauró la instalación anterior" not in result.stderr
    match = re.search(r"Copias de recuperación: (.+)$", result.stderr, re.MULTILINE)
    assert match is not None
    recovery = Path(match.group(1))
    assert recovery.is_dir()
    assert (recovery / "backup-image").read_bytes() == b"previous image for rm recovery\n"
    assert installed_image.read_bytes() == b"previous image for rm recovery\n"


@requires_real_appimage
def test_appimage_install_preserves_config_and_autostart(tmp_path: Path):
    home = tmp_path / "home"
    config = home / ".config/warp-control/config.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"accent":"#123456"}')
    autostart = home / ".config/autostart/com.devruby.warpcontrol.desktop"
    autostart.parent.mkdir(parents=True)
    autostart_content = "[Desktop Entry]\nExec=warp-control --background\n"
    autostart.write_text(autostart_content)
    sentinels = {
        home / ".local/bin/warp-cli": "user WARP command sentinel\n",
        home / ".local/share/warp-control/native-package.txt": "native package sentinel\n",
        home / ".local/lib/warp-control/legacy-install.txt": "legacy install sentinel\n",
    }
    for path, content in sentinels.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    result = run_script(
        "scripts/install.sh",
        "--yes",
        "--package",
        str(REAL_APPIMAGE),
        env={
            "WARP_CONTROL_OS_RELEASE": str(os_release(tmp_path, "fedora")),
            "HOME": str(home),
        },
    )
    assert result.returncode == 0, result.stderr
    assert config.read_text() == '{"accent":"#123456"}'
    assert autostart.read_text() == autostart_content
    for path, content in sentinels.items():
        assert path.read_text() == content


@requires_real_appimage
def test_appimage_repeat_install_is_idempotent(tmp_path: Path):
    home = tmp_path / "home"
    env = {
        "WARP_CONTROL_OS_RELEASE": str(os_release(tmp_path, "fedora")),
        "HOME": str(home),
    }
    first = run_script("scripts/install.sh", "--yes", "--package", str(REAL_APPIMAGE), env=env)
    assert first.returncode == 0, first.stderr
    installed_image = home / ".local/opt/warp-control/WARP-Control-2.0.0-x86_64.AppImage"

    second = run_script("scripts/install.sh", "--yes", "--package", str(REAL_APPIMAGE), env=env)
    assert second.returncode == 0, second.stderr
    assert installed_image.is_file()
    assert not installed_image.is_symlink()
    launcher = home / ".local/bin/warp-control"
    assert str(installed_image) in launcher.read_text()
    assert installed_image.stat().st_mode & stat.S_IXUSR


@requires_real_appimage
def test_renamed_real_appimage_repeat_install_uses_managed_local_launcher(tmp_path: Path):
    renamed = tmp_path / "downloaded-release.AppImage"
    shutil.copy2(REAL_APPIMAGE, renamed)
    renamed.chmod(0o755)
    home = tmp_path / "home"
    env = {
        "WARP_CONTROL_OS_RELEASE": str(os_release(tmp_path, "opensuse")),
        "HOME": str(home),
    }
    first = run_script("scripts/install.sh", "--yes", "--package", str(renamed), env=env)
    assert first.returncode == 0, first.stderr
    second = run_script("scripts/install.sh", "--yes", "--package", str(renamed), env=env)
    assert second.returncode == 0, second.stderr
    local_image = home / f".local/opt/warp-control/WARP-Control-local-{HOST_MACHINE}.AppImage"
    launcher = home / ".local/bin/warp-control"
    assert local_image.is_file()
    assert str(local_image) in launcher.read_text()
