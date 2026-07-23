from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[2]
APPIMAGE_DIR = ROOT / "packaging/appimage"
ENTRYPOINT = APPIMAGE_DIR / "entrypoint.py"
SPEC = APPIMAGE_DIR / "warp-control.spec"
APPRUN = APPIMAGE_DIR / "AppRun"
DESKTOP = APPIMAGE_DIR / "com.robler.warpcontrol.desktop"
APPIMAGETOOL_SHA256 = APPIMAGE_DIR / "appimagetool.sha256"
RUNTIME_SHA256 = APPIMAGE_DIR / "runtime.sha256"
BUILDER = ROOT / "scripts/build-appimage.sh"
TREE_VERIFIER = APPIMAGE_DIR / "verify_tree.py"

FORBIDDEN_TOKENS = (
    "usr/libexec/warp-control",
    "usr/share/polkit-1",
    "warp-cli",
    "warp-svc",
    "dnf",
    "apt-get",
    "pacman",
)

GI_HIDDEN_IMPORTS = (
    "Gtk",
    "Gdk",
    "GLib",
    "Gio",
)


def _read(path: Path) -> str:
    assert path.is_file(), f"missing required artifact: {path}"
    return path.read_text(encoding="utf-8")


def _run_builder(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(BUILDER), *arguments],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_tree_verifier(
    staged: Path, extracted: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(ROOT / ".venv/bin/python"), str(TREE_VERIFIER), str(staged), str(extracted)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


# --- entrypoint -------------------------------------------------------


def test_entrypoint_calls_warp_control_main() -> None:
    text = _read(ENTRYPOINT)
    assert "from warp_control.__main__ import main" in text
    assert "raise SystemExit(main())" in text


# --- desktop file: portable Exec --------------------------------------


def test_desktop_entry_uses_portable_exec() -> None:
    text = _read(DESKTOP)
    assert re.search(r"^Exec=warp-control$", text, flags=re.MULTILINE), (
        "AppImage desktop entry must launch via bare command, not an "
        "absolute native path"
    )
    assert "Exec=/usr/bin/warp-control" not in text
    assert re.search(r"^Name=WARP Control$", text, flags=re.MULTILINE)
    assert re.search(r"^Icon=com\.robler\.warpcontrol$", text, flags=re.MULTILINE)
    assert re.search(r"^Type=Application$", text, flags=re.MULTILINE)


# --- AppRun: environment exports and exec ------------------------------


def test_apprun_preserves_original_appimage_path() -> None:
    text = _read(APPRUN)
    assert 'WARP_CONTROL_EXECUTABLE="${APPIMAGE' in text
    assert "WARP_CONTROL_DESKTOP_FILE" in text
    assert 'exec "$APPDIR/usr/bin/warp-control" "$@"' in text


def test_apprun_exports_desktop_file_under_appdir() -> None:
    text = _read(APPRUN)
    assert (
        'export WARP_CONTROL_DESKTOP_FILE='
        '"$APPDIR/usr/share/applications/com.robler.warpcontrol.desktop"'
    ) in text


def test_apprun_is_a_strict_posix_shell_script() -> None:
    text = _read(APPRUN)
    assert text.startswith("#!/usr/bin/env sh") or text.startswith("#!/bin/sh")
    assert "set -eu" in text


def test_apprun_replaces_host_runtime_paths(tmp_path: Path) -> None:
    appdir = tmp_path / "AppDir"
    binary = appdir / "usr/bin/warp-control"
    binary.parent.mkdir(parents=True)
    capture = tmp_path / "environment"
    shutil.copy2(APPRUN, appdir / "AppRun")
    (appdir / "AppRun").chmod(0o755)
    binary.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$LD_LIBRARY_PATH\" \"$GI_TYPELIB_PATH\" "
        "\"$XDG_DATA_DIRS\" \"$WARP_CONTROL_EXECUTABLE\" "
        "\"$WARP_CONTROL_DESKTOP_FILE\" >\"$CAPTURE\"\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    image = tmp_path / "WARP-Control.AppImage"

    result = subprocess.run(
        [str(appdir / "AppRun"), "--smoke-test"],
        env={
            **os.environ,
            "APPDIR": str(appdir),
            "APPIMAGE": str(image),
            "CAPTURE": str(capture),
            "LD_LIBRARY_PATH": "/host/evil/lib",
            "GI_TYPELIB_PATH": "/host/evil/typelib",
            "XDG_DATA_DIRS": "/host/evil/share",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert capture.read_text(encoding="utf-8").splitlines() == [
        str(appdir / "usr/bin/_internal"),
        str(appdir / "usr/bin/_internal/gi_typelibs"),
        f"{appdir}/usr/bin/_internal/share:{appdir}/usr/share",
        str(image),
        str(appdir / "usr/share/applications/com.robler.warpcontrol.desktop"),
    ]


# --- extracted tree allowlist -----------------------------------------


def _safe_tree(root: Path) -> None:
    executable = root / "usr/bin/warp-control"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"portable binary\n")
    executable.chmod(0o755)
    icon = root / "usr/share/icons/app.svg"
    icon.parent.mkdir(parents=True)
    icon.write_text("<svg/>\n", encoding="utf-8")
    icon.chmod(0o644)
    (root / "launcher").symlink_to("usr/bin/warp-control")


def test_tree_verifier_accepts_an_identical_safe_extraction(tmp_path: Path) -> None:
    staged = tmp_path / "staged"
    extracted = tmp_path / "extracted"
    _safe_tree(staged)
    shutil.copytree(staged, extracted, symlinks=True)

    result = _run_tree_verifier(staged, extracted)

    assert result.returncode == 0, result.stderr


def test_tree_verifier_rejects_an_unexpected_renamed_binary(tmp_path: Path) -> None:
    staged = tmp_path / "staged"
    extracted = tmp_path / "extracted"
    _safe_tree(staged)
    shutil.copytree(staged, extracted, symlinks=True)
    binary = extracted / "usr/bin/warp-control"
    binary.rename(extracted / "usr/bin/unexpected-tool")

    result = _run_tree_verifier(staged, extracted)

    assert result.returncode != 0
    assert "unexpected" in result.stderr.lower()
    assert "missing" in result.stderr.lower()


def test_tree_verifier_rejects_changed_file_content(tmp_path: Path) -> None:
    staged = tmp_path / "staged"
    extracted = tmp_path / "extracted"
    _safe_tree(staged)
    shutil.copytree(staged, extracted, symlinks=True)
    (extracted / "usr/bin/warp-control").write_bytes(b"changed\n")

    result = _run_tree_verifier(staged, extracted)

    assert result.returncode != 0
    assert "content" in result.stderr.lower()


def test_tree_verifier_rejects_a_missing_file(tmp_path: Path) -> None:
    staged = tmp_path / "staged"
    extracted = tmp_path / "extracted"
    _safe_tree(staged)
    shutil.copytree(staged, extracted, symlinks=True)
    (extracted / "usr/share/icons/app.svg").unlink()

    result = _run_tree_verifier(staged, extracted)

    assert result.returncode != 0
    assert "missing" in result.stderr.lower()


def test_tree_verifier_rejects_an_escaping_symlink(tmp_path: Path) -> None:
    staged = tmp_path / "staged"
    extracted = tmp_path / "extracted"
    _safe_tree(staged)
    (staged / "escape").symlink_to("../outside")
    shutil.copytree(staged, extracted, symlinks=True)

    result = _run_tree_verifier(staged, extracted)

    assert result.returncode != 0
    assert "escaping symlink" in result.stderr.lower()


# --- PyInstaller spec: onedir, data collection, GI hidden imports ------


def test_spec_collects_warp_control_data_files() -> None:
    text = _read(SPEC)
    assert 'collect_data_files("warp_control")' in text


def test_spec_adds_source_package_before_collecting_data() -> None:
    text = _read(SPEC)
    source_setup = text.index("sys.path.insert")
    data_collection = text.index('collect_data_files("warp_control")')
    assert source_setup < data_collection


def test_spec_builds_onedir_collect() -> None:
    text = _read(SPEC)
    assert "COLLECT(" in text
    assert "onedir" in text.lower() or "COLLECT(" in text


def test_spec_includes_required_gi_hidden_imports() -> None:
    text = _read(SPEC)
    for module in GI_HIDDEN_IMPORTS:
        assert re.search(rf"""['"]gi\.repository\.{module}['"]""", text), (
            f"missing hidden import for gi.repository.{module}"
        )


def test_spec_excludes_libexec_and_privileged_helpers() -> None:
    text = _read(SPEC)
    assert "libexec" not in text
    assert "warp-cli" not in text
    assert "warp-svc" not in text
    assert "polkit" not in text.lower()


# --- appimagetool.sha256: pinned per-architecture digests --------------


def test_appimagetool_sha256_pins_every_supported_architecture() -> None:
    text = _read(APPIMAGETOOL_SHA256)
    lines = [line for line in text.splitlines() if line.strip()]
    assert lines, "appimagetool.sha256 must not be empty"

    entries: dict[str, str] = {}
    for line in lines:
        match = re.match(r"^([0-9a-f]{64})\s+\S*appimagetool-(x86_64|aarch64)\S*$", line)
        assert match is not None, f"unexpected line format: {line!r}"
        digest, arch = match.groups()
        assert arch not in entries, f"duplicate pinned digest for {arch}"
        entries[arch] = digest

    assert entries.keys() == {"x86_64", "aarch64"}
    assert entries == {
        "x86_64": "a6d71e2b6cd66f8e8d16c37ad164658985e0cf5fcaa950c90a482890cb9d13e0",
        "aarch64": "1b00524ba8c6b678dc15ef88a5c25ec24def36cdfc7e3abb32ddcd068e8007fe",
    }


def test_runtime_sha256_pins_every_supported_architecture() -> None:
    text = _read(RUNTIME_SHA256)
    entries: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64})\s+runtime-(x86_64|aarch64)", line)
        assert match is not None, f"unexpected line format: {line!r}"
        digest, arch = match.groups()
        assert arch not in entries
        entries[arch] = digest
    assert entries == {
        "x86_64": "1cc49bcf1e2ccd593c379adb17c9f85a36d619088296504de95b1d06215aebbf",
        "aarch64": "7d5d772b7c32f0c84caf0a452a3072a5709027d7eac5856feb89a7a7a8881372",
    }


# --- build-appimage.sh: builder contract --------------------------------


def test_builder_script_exists_and_is_executable() -> None:
    assert BUILDER.is_file()
    mode = BUILDER.stat().st_mode
    assert mode & stat.S_IXUSR, "scripts/build-appimage.sh must be executable"


def test_builder_uses_strict_bash_mode() -> None:
    text = _read(BUILDER)
    assert text.startswith("#!/usr/bin/bash") or text.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in text


def test_builder_declares_required_cli_flags() -> None:
    text = _read(BUILDER)
    assert "--arch" in text
    assert "--appimagetool" in text
    assert "--runtime-file" in text
    assert "--output-dir" in text


def test_builder_supplies_explicit_runtime_to_prevent_hidden_download() -> None:
    text = _read(BUILDER)
    invocation = re.search(
        r'"\$private_appimagetool"[^\n]*--runtime-file[^\n]*"\$private_runtime"',
        text,
    )
    assert invocation is not None
    assert "runtime.sha256" in text


def test_builder_validates_architecture_against_native_machine() -> None:
    text = _read(BUILDER)
    assert re.search(r"x86_64\|aarch64", text) or (
        "x86_64" in text and "aarch64" in text
    )
    assert "uname -m" in text


def test_builder_maps_aarch64_to_appimagekit_arch_name() -> None:
    text = _read(BUILDER)
    assert re.search(r"x86_64\)\s+appimage_arch=x86_64", text)
    assert re.search(r"aarch64\)\s+appimage_arch=arm_aarch64", text)
    assert 'ARCH=$appimage_arch "$private_appimagetool"' in text


def test_builder_rejects_architecture_mismatch_with_host() -> None:
    text = _read(BUILDER)
    assert "uname -m" in text
    assert re.search(r"exit 1|exit \"?\$", text)


def test_builder_requires_regular_executable_appimagetool() -> None:
    text = _read(BUILDER)
    assert "-f " in text or "[[ -f " in text, "must check appimagetool is a regular file"
    assert "-x " in text or "[[ -x " in text, "must check appimagetool is executable"
    assert "-L " in text or "[[ ! -L " in text, "must reject a symlinked appimagetool"


def test_builder_never_downloads_tools() -> None:
    text = _read(BUILDER)
    for downloader in ("curl", "wget", "http://", "https://"):
        assert downloader not in text, f"builder must not download via {downloader}"


def test_builder_verifies_appimagetool_checksum() -> None:
    text = _read(BUILDER)
    assert "sha256sum" in text
    assert "appimagetool.sha256" in text


def test_builder_creates_private_appdir() -> None:
    text = _read(BUILDER)
    assert "mktemp -d" in text
    assert re.search(r"chmod (0?700|u=rwx,go=)", text), (
        "AppDir staging directory must be created with private permissions"
    )


def test_builder_scans_extraction_for_forbidden_paths() -> None:
    text = _read(BUILDER)
    for token in FORBIDDEN_TOKENS:
        assert token in text, f"builder must scan for forbidden token {token!r}"


def test_builder_extracts_and_runs_smoke_test() -> None:
    text = _read(BUILDER)
    assert "--appimage-extract-and-run" in text
    assert "--smoke-test" in text


def test_builder_runs_pyinstaller_against_warp_control_spec() -> None:
    text = _read(BUILDER)
    assert "pyinstaller" in text.lower()
    assert "warp-control.spec" in text


def test_builder_rejects_missing_arguments_without_starting_a_build() -> None:
    result = _run_builder()
    assert result.returncode == 2
    assert "Usage:" in result.stderr


def test_builder_rejects_duplicate_runtime_argument(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    _write_runtime(runtime)
    result = _run_builder(
        "--arch",
        _native_arch(),
        "--appimagetool",
        str(tmp_path / "tool"),
        "--runtime-file",
        str(runtime),
        "--runtime-file",
        str(runtime),
        "--output-dir",
        str(tmp_path),
    )
    assert result.returncode == 2
    assert "only once" in result.stderr.lower()


def test_builder_rejects_unknown_architecture_before_tool_use(tmp_path: Path) -> None:
    fake_tool = tmp_path / "appimagetool"
    fake_tool.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    fake_tool.chmod(0o700)

    result = _run_builder(
        "--arch",
        "mips64",
        "--appimagetool",
        str(fake_tool),
        "--runtime-file",
        str(tmp_path / "runtime"),
        "--output-dir",
        str(tmp_path),
    )

    assert result.returncode == 2
    assert "unsupported architecture" in result.stderr.lower()


def test_builder_rejects_symlinked_appimagetool(tmp_path: Path) -> None:
    fake_tool = tmp_path / "real-appimagetool"
    fake_tool.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    fake_tool.chmod(0o700)
    link = tmp_path / "appimagetool"
    link.symlink_to(fake_tool)

    machine = subprocess.run(
        ["uname", "-m"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    arch = "aarch64" if machine in {"aarch64", "arm64"} else "x86_64"
    runtime = tmp_path / "runtime"
    _write_runtime(runtime, arch)
    result = _run_builder(
        "--arch",
        arch,
        "--appimagetool",
        str(link),
        "--runtime-file",
        str(runtime),
        "--output-dir",
        str(tmp_path),
    )

    assert result.returncode == 2
    assert "symlink" in result.stderr.lower()


def _native_arch() -> str:
    machine = subprocess.run(
        ["uname", "-m"], text=True, capture_output=True, check=True
    ).stdout.strip()
    return "aarch64" if machine in {"aarch64", "arm64"} else "x86_64"


def _write_runtime(path: Path, arch: str | None = None) -> None:
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    machine = 183 if (arch or _native_arch()) == "aarch64" else 62
    header[18:20] = machine.to_bytes(2, "little")
    path.write_bytes(header)


def _runtime_arguments(tmp_path: Path) -> tuple[str, str]:
    runtime = tmp_path / "runtime"
    _write_runtime(runtime)
    return "--runtime-file", str(runtime)


def test_builder_rejects_native_architecture_mismatch(tmp_path: Path) -> None:
    tool = tmp_path / "appimagetool"
    tool.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    tool.chmod(0o700)
    opposite = "aarch64" if _native_arch() == "x86_64" else "x86_64"

    result = _run_builder(
        "--arch",
        opposite,
        "--appimagetool",
        str(tool),
        *_runtime_arguments(tmp_path),
        "--output-dir",
        str(tmp_path),
    )

    assert result.returncode == 1
    assert "requested" in result.stderr.lower()


def test_builder_rejects_checksum_mismatch(tmp_path: Path) -> None:
    tool = tmp_path / "appimagetool"
    tool.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    tool.chmod(0o700)

    result = _run_builder(
        "--arch",
        _native_arch(),
        "--appimagetool",
        str(tool),
        *_runtime_arguments(tmp_path),
        "--output-dir",
        str(tmp_path),
    )

    assert result.returncode == 1
    assert "checksum" in result.stderr.lower()


def test_builder_rejects_nonregular_or_nonexecutable_tool(tmp_path: Path) -> None:
    directory_tool = tmp_path / "directory-tool"
    directory_tool.mkdir()
    plain_tool = tmp_path / "plain-tool"
    plain_tool.write_text("not executable", encoding="utf-8")

    for tool in (directory_tool, plain_tool):
        result = _run_builder(
            "--arch",
            _native_arch(),
            "--appimagetool",
            str(tool),
            *_runtime_arguments(tmp_path),
            "--output-dir",
            str(tmp_path),
        )
        assert result.returncode == 2
        assert "regular executable" in result.stderr.lower()


def test_builder_rejects_unsafe_runtime_file(tmp_path: Path) -> None:
    tool = tmp_path / "appimagetool"
    tool.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    tool.chmod(0o700)
    runtime_directory = tmp_path / "runtime-directory"
    runtime_directory.mkdir()
    real_runtime = tmp_path / "real-runtime"
    _write_runtime(real_runtime)
    runtime_link = tmp_path / "runtime-link"
    runtime_link.symlink_to(real_runtime)

    for runtime in (runtime_directory, runtime_link):
        result = _run_builder(
            "--arch",
            _native_arch(),
            "--appimagetool",
            str(tool),
            "--runtime-file",
            str(runtime),
            "--output-dir",
            str(tmp_path),
        )
        assert result.returncode == 2
        assert "runtime" in result.stderr.lower()


def test_builder_rejects_runtime_for_wrong_elf_architecture(tmp_path: Path) -> None:
    tool = tmp_path / "appimagetool"
    tool.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    tool.chmod(0o700)
    runtime = tmp_path / "runtime"
    opposite = "aarch64" if _native_arch() == "x86_64" else "x86_64"
    _write_runtime(runtime, opposite)

    result = _run_builder(
        "--arch",
        _native_arch(),
        "--appimagetool",
        str(tool),
        "--runtime-file",
        str(runtime),
        "--output-dir",
        str(tmp_path),
    )

    assert result.returncode == 2
    assert "elf architecture" in result.stderr.lower()


def test_builder_rejects_symlink_in_output_ancestry(tmp_path: Path) -> None:
    tool = tmp_path / "appimagetool"
    tool.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    tool.chmod(0o700)
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)

    result = _run_builder(
        "--arch",
        _native_arch(),
        "--appimagetool",
        str(tool),
        *_runtime_arguments(tmp_path),
        "--output-dir",
        str(linked_parent / "dist"),
    )

    assert result.returncode == 2
    assert "ancestry" in result.stderr.lower()


def test_builder_fake_tool_exercises_extract_verify_and_smoke(tmp_path: Path) -> None:
    fake_repo = tmp_path / "repo"
    for relative in (
        "packaging/appimage/AppRun",
        "packaging/appimage/com.robler.warpcontrol.desktop",
        "packaging/appimage/warp-control.spec",
        "packaging/appimage/verify_tree.py",
        "data/icons/com.robler.warpcontrol.svg",
        "data/com.robler.warpcontrol.metainfo.xml",
        "scripts/build-appimage.sh",
    ):
        source = ROOT / relative
        target = fake_repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    (fake_repo / "packaging/release.env").write_text(
        "VERSION=2.0.0\nSOURCE_DATE_EPOCH=1784678400\n", encoding="utf-8"
    )
    fake_python = fake_repo / ".venv/bin/python"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text(
        "#!/bin/bash\nset -eu\n"
        "if [[ ${1:-} == -c ]]; then exit 0; fi\n"
        "dist=''\n"
        "while (( $# )); do\n"
        "  if [[ $1 == --distpath ]]; then dist=$2; shift 2; else shift; fi\n"
        "done\n"
        "payload=$dist/warp-control; mkdir -p \"$payload/_internal/gi_typelibs\"\n"
        "for f in Gtk-3.0 Gdk-3.0 GLib-2.0 Gio-2.0 AyatanaAppIndicator3-0.1; do "
        ": >\"$payload/_internal/gi_typelibs/$f.typelib\"; done\n"
        "for f in libgtk-3.so.0 libgdk-3.so.0 libgobject-2.0.so.0 "
        "libgio-2.0.so.0 libgdk_pixbuf-2.0.so.0 libcairo.so.2 "
        "libayatana-appindicator3.so.1; do : >\"$payload/_internal/$f\"; done\n"
        "printf '#!/bin/sh\\nprintf smoke >>\"$FAKE_TOOL_LOG\"\\n' "
        ">\"$payload/warp-control\"; chmod 755 \"$payload/warp-control\"\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    runner = fake_repo / "fake-image-runner"
    runner.write_text(
        "#!/bin/sh\nset -eu\nprintf '%s\\n' \"$1\" >>\"$FAKE_TOOL_LOG\"\n"
        "case $1 in\n"
        "  --appimage-extract) cp -a \"$0.contents\" \"$PWD/squashfs-root\" ;;\n"
        "  --appimage-extract-and-run) shift; APPDIR=\"$0.contents\" "
        "APPIMAGE=\"$0\" \"$0.contents/AppRun\" \"$@\" ;;\n"
        "  *) exit 90 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    runner.chmod(0o755)
    tool = fake_repo / "appimagetool-x86_64.AppImage"
    tool.write_text(
        "#!/bin/sh\nset -eu\nprintf 'tool:%s\\narch:%s\\n' \"$0\" \"$ARCH\" "
        ">>\"$FAKE_TOOL_LOG\"\n"
        "[ \"$1\" = --appimage-extract-and-run ]\n"
        "[ \"$2\" = --runtime-file ]\n"
        "printf 'runtime:%s\\n' \"$3\" >>\"$FAKE_TOOL_LOG\"\n"
        "cp -a \"$4\" \"$5.contents\"\ncp \"$FAKE_IMAGE_RUNNER\" \"$5\"\n",
        encoding="utf-8",
    )
    tool.chmod(0o755)
    shell = shutil.which("dash") or shutil.which("sh")
    assert shell is not None
    syntax = subprocess.run(
        [shell, "-n", str(tool)], text=True, capture_output=True, check=False
    )
    assert syntax.returncode == 0, syntax.stderr
    digest = hashlib.sha256(tool.read_bytes()).hexdigest()
    (fake_repo / "packaging/appimage/appimagetool.sha256").write_text(
        f"{digest}  appimagetool-{_native_arch()}.AppImage\n", encoding="utf-8"
    )
    runtime = fake_repo / f"runtime-{_native_arch()}"
    _write_runtime(runtime)
    runtime_digest = hashlib.sha256(runtime.read_bytes()).hexdigest()
    runtime_checksums = fake_repo / "packaging/appimage/runtime.sha256"
    runtime_checksums.write_text(
        f"{'0' * 64}  runtime-{_native_arch()}\n", encoding="utf-8"
    )
    output = fake_repo / "dist"
    output.mkdir()
    log = tmp_path / "handoff.log"

    command = [
        str(fake_repo / "scripts/build-appimage.sh"),
        "--arch",
        _native_arch(),
        "--appimagetool",
        str(tool),
        "--runtime-file",
        str(runtime),
        "--output-dir",
        str(output),
    ]
    environment = {
        **os.environ,
        "FAKE_TOOL_LOG": str(log),
        "FAKE_IMAGE_RUNNER": str(runner),
    }
    checksum_failure = subprocess.run(
        command,
        cwd=fake_repo,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert checksum_failure.returncode == 1
    assert "runtime checksum" in checksum_failure.stderr.lower()
    runtime_checksums.write_text(
        f"{runtime_digest}  runtime-{_native_arch()}\n", encoding="utf-8"
    )

    result = subprocess.run(
        command,
        cwd=fake_repo,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (output / f"WARP-Control-2.0.0-{_native_arch()}.AppImage").is_file()
    handoff = log.read_text(encoding="utf-8")
    assert "--appimage-extract\n" in handoff
    assert "--appimage-extract-and-run\n" in handoff
    assert "smoke" in handoff
    assert "tool:/tmp/warp-control-appimage." in handoff
    assert f"tool:{tool}" not in handoff
    assert "runtime:/tmp/warp-control-appimage." in handoff
    assert f"runtime:{runtime}" not in handoff
    expected_appimage_arch = "arm_aarch64" if _native_arch() == "aarch64" else "x86_64"
    assert f"arch:{expected_appimage_arch}\n" in handoff
