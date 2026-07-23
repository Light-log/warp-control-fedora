# Linux Release Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish verified WARP Control artifacts for Fedora/RHEL, Debian/Ubuntu, Arch and other glibc desktop Linux systems through x86_64/aarch64 AppImages while preserving existing filesystem layouts.

**Architecture:** Keep the Python package and native package definitions, add a PyInstaller-based AppDir/AppImage layer, extend the secure installer with an unprivileged AppImage path, and gate publication on every native/portable build. Native packages retain PolicyKit only where Cloudflare has an official repository; portable/community installs never elevate to install WARP.

**Tech Stack:** Python 3.9+, GTK 3/PyGObject, Bash, PyInstaller, AppImageKit, RPM, debhelper, makepkg, GitHub Actions, pytest and Ruff.

---

## File map

- Release contract: `packaging/release.env`, `scripts/update-release-metadata.py`, `scripts/build-source-tarball.sh`, `packaging/arch/PKGBUILD`.
- Portable runtime: `src/warp_control/runtime.py`, `src/warp_control/services/autostart.py`, `src/warp_control/app.py`.
- AppImage: `packaging/appimage/`, `scripts/build-appimage.sh`, `tests/packaging/test_appimage.py`.
- Installer: `scripts/install.sh`, `tests/shell/test_scripts.py`, `tests/shell/install.bats`.
- Automation: `.github/workflows/packages.yml`, `.github/workflows/release.yml`, `scripts/verify-release.sh`.
- Documentation: `README.md`, `docs/INSTALL.md`, `docs/SUPPORT.md`, `CHANGELOG.md`, `PROJECT_CONTEXT.md`, `NEXT_STEPS.md`.

### Task 1: Deterministic release source and Arch package

**Files:**
- Create: `packaging/release.env`
- Create: `scripts/update-release-metadata.py`
- Modify: `scripts/build-source-tarball.sh`
- Modify: `packaging/arch/PKGBUILD`
- Modify: `tests/packaging/test_installed_layout.py`
- Modify: `tests/packaging/test_metadata.py`

- [ ] **Step 1: Write failing release-contract tests**

Require validated `VERSION`/`SOURCE_DATE_EPOCH`, an archive excluding the self-referential PKGBUILD, and a release URL plus real checksum:

```python
def test_arch_uses_checksummed_release_source() -> None:
    text = (ROOT / "packaging/arch/PKGBUILD").read_text(encoding="utf-8")
    assert "releases/download/v$pkgver/warp-control-$pkgver.tar.gz" in text
    assert "source_commit" not in text
    assert "git+" not in text
    assert "SKIP" not in text
    assert re.search(r"sha256sums=\('([0-9a-f]{64})'\)", text)
```

Extend the tarball test with:

```python
assert "warp-control-2.0.0/packaging/arch/PKGBUILD" not in names
```

- [ ] **Step 2: Prove the tests fail**

Run: `.venv/bin/pytest tests/packaging/test_metadata.py tests/packaging/test_installed_layout.py -q`

Expected: FAIL on the current VCS source and `SKIP`.

- [ ] **Step 3: Add stable release data**

Create data (never shell-source it):

```text
VERSION=2.0.0
SOURCE_DATE_EPOCH=1784678400
```

Update the tarball builder to parse anchored values, require the version to match `pyproject.toml`, use the stable epoch by default, and exclude `packaging/arch/PKGBUILD` via Git pathspec while retaining dirty-check, gzip `-n`, sorted content and normalized ownership.

- [ ] **Step 4: Implement atomic metadata update**

Expose `sha256(path: Path) -> str`, `update_pkgbuild(path: Path, *, version: str, digest: str) -> None` and `main(argv: Sequence[str] | None = None) -> int`. `sha256` streams 1 MiB chunks. `update_pkgbuild` validates `version` with `^[0-9]+\.[0-9]+\.[0-9]+$` and `digest` with `^[0-9a-f]{64}$`, requires exactly one anchored `pkgver=` and `sha256sums=` match, refuses a symlink target, writes a sibling `0600` temporary file, copies the original mode, calls `fsync`, then `os.replace`. `main` requires `--source-tarball PATH`, verifies basename/version against `release.env`, and returns 2 for validation failures without changing PKGBUILD.

- [ ] **Step 5: Replace the Arch VCS source**

Use:

```bash
source=("$pkgname-$pkgver.tar.gz::$url/releases/download/v$pkgver/$pkgname-$pkgver.tar.gz")
```

All functions use `cd "$srcdir/$pkgname-$pkgver"`; `sha256sums` receives the lowercase digest produced by `update-release-metadata.py`. Build the archive, run the updater, commit the checksum change, rebuild from the clean checkout with the same epoch, and verify the digest remains identical because PKGBUILD is excluded.

- [ ] **Step 6: Verify and commit**

Run:

```bash
.venv/bin/pytest tests/packaging/test_metadata.py tests/packaging/test_installed_layout.py -q
.venv/bin/ruff check scripts/update-release-metadata.py tests/packaging
```

Expected: PASS. Commit: `build: make Arch release sources reproducible`.

### Task 2: Portable runtime paths without moving user data

**Files:**
- Create: `src/warp_control/runtime.py`
- Create: `tests/test_runtime.py`
- Modify: `src/warp_control/services/autostart.py`
- Modify: `src/warp_control/app.py`
- Modify: `tests/services/test_autostart.py`

- [ ] **Step 1: Write failing path tests**

```python
def test_appimage_runtime_uses_original_file(tmp_path: Path) -> None:
    image = tmp_path / "WARP-Control.AppImage"
    desktop = tmp_path / "com.devruby.warpcontrol.desktop"
    paths = RuntimePaths.from_environment({
        "APPIMAGE": str(image),
        "WARP_CONTROL_DESKTOP_FILE": str(desktop),
    })
    assert paths.executable == image
    assert paths.desktop_source == desktop
    assert paths.portable is True
```

Also cover native defaults and rejection of relative/control-character paths.

- [ ] **Step 2: Prove failure**

Run: `.venv/bin/pytest tests/test_runtime.py tests/services/test_autostart.py -q`

Expected: FAIL because `RuntimePaths` does not exist and autostart assumes `/usr/bin`.

- [ ] **Step 3: Implement immutable path resolution**

```python
def _absolute_path(value: str, label: str) -> Path:
    if not value or any(character in value for character in "\r\n\0"):
        raise ValueError(f"{label} is invalid")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute")
    return path


@dataclass(frozen=True)
class RuntimePaths:
    executable: Path
    desktop_source: Path
    portable: bool

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] = os.environ
    ) -> "RuntimePaths":
        appimage = environment.get("APPIMAGE")
        if not appimage:
            return cls(
                Path("/usr/bin/warp-control"),
                Path("/usr/share/applications/com.devruby.warpcontrol.desktop"),
                False,
            )
        executable = _absolute_path(appimage, "APPIMAGE")
        desktop = _absolute_path(
            environment.get("WARP_CONTROL_DESKTOP_FILE", ""),
            "WARP_CONTROL_DESKTOP_FILE",
        )
        return cls(executable, desktop, True)
```

Native defaults remain `/usr/bin/warp-control` and `/usr/share/applications/com.devruby.warpcontrol.desktop`. Portable mode requires an absolute `APPIMAGE` and never persists `/tmp/.mount_*`.

- [ ] **Step 4: Inject paths into autostart**

In `_build_runtime`, create `RuntimePaths.from_environment()` and pass its executable/desktop source to `AutostartService`. Do not change XDG config or autostart destinations.

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/pytest tests/test_runtime.py tests/services/test_autostart.py tests/test_app_controller.py -q`

Expected: PASS. Commit: `feat: support stable portable runtime paths`.

### Task 3: Self-contained GTK AppImage

**Files:**
- Create: `packaging/appimage/entrypoint.py`
- Create: `packaging/appimage/warp-control.spec`
- Create: `packaging/appimage/AppRun`
- Create: `packaging/appimage/com.devruby.warpcontrol.desktop`
- Create: `packaging/appimage/appimagetool.sha256`
- Create: `scripts/build-appimage.sh`
- Create: `tests/packaging/test_appimage.py`
- Modify: `MANIFEST.in`

- [ ] **Step 1: Write failing static contract tests**

Assert portable `Exec=warp-control`, AppRun environment, PyInstaller asset/GI collection, pinned appimagetool digests and architecture rejection:

```python
def test_apprun_preserves_original_appimage_path() -> None:
    text = (ROOT / "packaging/appimage/AppRun").read_text(encoding="utf-8")
    assert 'WARP_CONTROL_EXECUTABLE="${APPIMAGE' in text
    assert "WARP_CONTROL_DESKTOP_FILE" in text
    assert 'exec "$APPDIR/usr/bin/warp-control" "$@"' in text
```

- [ ] **Step 2: Prove failure**

Run: `.venv/bin/pytest tests/packaging/test_appimage.py -q`

Expected: FAIL because AppImage files are absent.

- [ ] **Step 3: Add PyInstaller entry/spec**

`entrypoint.py` exits through `warp_control.__main__.main`. The spec uses `collect_data_files("warp_control")`, GI hidden imports and an onedir `COLLECT`. It must not collect `libexec`, PolicyKit, WARP or package managers.

- [ ] **Step 4: Add AppRun and desktop metadata**

AppRun exports:

```bash
export WARP_CONTROL_EXECUTABLE="${APPIMAGE:-$APPDIR/AppRun}"
export WARP_CONTROL_DESKTOP_FILE="$APPDIR/usr/share/applications/com.devruby.warpcontrol.desktop"
exec "$APPDIR/usr/bin/warp-control" "$@"
```

- [ ] **Step 5: Implement the builder**

`build-appimage.sh --arch x86_64|aarch64 --appimagetool PATH --runtime-file PATH --output-dir PATH` validates the native architecture plus pinned regular tool/runtime inputs, creates an inode-validated private AppDir, runs PyInstaller, installs fixed-mode metadata/assets, invokes appimagetool with the explicit Type 2 runtime, extracts the result, scans its allowlist and runs `--appimage-extract-and-run --smoke-test`. It never downloads build inputs.

- [ ] **Step 6: Verify host build and commit**

Run:

```bash
.venv/bin/pytest tests/packaging/test_appimage.py -q
bash -n scripts/build-appimage.sh packaging/appimage/AppRun
scripts/build-appimage.sh --arch x86_64 --appimagetool "$PWD/.tools/appimagetool-x86_64.AppImage" --runtime-file "$PWD/.tools/runtime-x86_64" --output-dir "$PWD/dist"
dist/WARP-Control-2.0.0-x86_64.AppImage --appimage-extract-and-run --smoke-test
```

Expected: PASS/exit 0. Commit: `build: add portable AppImage artifacts`.

### Task 4: Unprivileged AppImage installation

**Files:**
- Modify: `scripts/install.sh`
- Modify: `tests/shell/test_scripts.py`
- Modify: `tests/shell/install.bats`

- [ ] **Step 1: Write failing installer tests**

Use minimal ELF headers for dry-run/architecture cases (x86_64 `e_machine` bytes `3e 00`, aarch64 `b7 00`). Use the host AppImage produced in Task 3 for extraction, atomic replacement and preserved-config integration cases; do not invent a shell script that merely has an `.AppImage` suffix. Cover unknown distros, architecture mismatch, unsafe ancestry and no sudo:

```python
def test_appimage_dry_run_is_unprivileged_on_unknown_linux(tmp_path: Path):
    result = run_script(
        "scripts/install.sh", "--dry-run", "--package", str(appimage),
        env={"WARP_CONTROL_OS_RELEASE": str(os_release(tmp_path, "opensuse"))},
    )
    assert result.returncode == 0
    assert ".local/opt/warp-control" in result.stdout
    assert "sudo" not in result.stdout
```

- [ ] **Step 2: Prove failure**

Run: `.venv/bin/pytest tests/shell/test_scripts.py -q`

Expected: FAIL because unknown distros are rejected before format selection.

- [ ] **Step 3: Detect AppImage before distro family**

For explicit `.AppImage`, validate ELF magic/class/machine with `od`, accept only matching x86_64/aarch64 and bypass native family selection. Native formats retain the fail-closed os-release parser.

- [ ] **Step 4: Add atomic local integration**

Install beneath `${WARP_CONTROL_INSTALL_ROOT:-$HOME/.local}` (override accepted only when absolute) into:

```text
opt/warp-control/WARP-Control-<version>-<arch>.AppImage
bin/warp-control
share/applications/com.devruby.warpcontrol.desktop
share/icons/hicolor/scalable/apps/com.devruby.warpcontrol.svg
```

Snapshot first; extract only desktop/icon; rewrite `Exec=` to the local launcher. Replace the launcher only if absent or already pointing into `opt/warp-control`. Never touch config, autostart, WARP or native package files.

- [ ] **Step 5: Verify and commit**

Run:

```bash
.venv/bin/pytest tests/shell/test_scripts.py -q
bats tests/shell/install.bats
bash -n scripts/install.sh
```

Expected: PASS and fake sudo marker absent. Commit: `feat: install AppImages without privilege`.

### Task 5: Native package build/install matrices

**Files:**
- Modify: `.github/workflows/packages.yml`
- Modify: `packaging/rpm/warp-control.spec`
- Modify: `debian/control`
- Modify: `tests/packaging/test_metadata.py`

- [ ] **Step 1: Write failing workflow assertions**

Require Fedora 43/44, EL9/EL10-compatible, Ubuntu 22.04/24.04/26.04, Debian 12/13 and Arch jobs. Each must install its produced artifact into a matching clean root and run installed `/usr/bin/warp-control --smoke-test`.

- [ ] **Step 2: Prove missing coverage**

Run: `.venv/bin/pytest tests/packaging/test_metadata.py -q`

Expected: FAIL because the workflow currently has one Fedora and one Ubuntu build without install matrices.

- [ ] **Step 3: Build RPMs per target Python ABI**

Add a `source` job that creates and uploads the deterministic tarball once. Every native build downloads that exact artifact. Use one spec but separate `.fc43`, `.fc44`, `.el9` and `.el10` builds. Do not reuse a Fedora-built RPM on RHEL: generated `python(abi)` dependencies bind it to the build target. Enable EPEL on EL9/EL10; enable CRB only if the package solver demonstrates a required dependency. Install and smoke-test each RPM on the same major target.

- [ ] **Step 4: Build/install-test every supported DEB base**

For Ubuntu 22.04/24.04/26.04 and Debian 12/13, run `dpkg-buildpackage`, `lintian --fail-on error`, install with `apt-get` and run smoke test. Upload artifact names containing distro/version even though the package architecture is `all`.

- [ ] **Step 5: Build/install-test Arch**

Create an unprivileged builder, make a temporary PKGBUILD copy pointing to the deterministic local tarball, run `makepkg`, `namcap`, `pacman -U` and smoke test. Never modify the committed release PKGBUILD in CI.

- [ ] **Step 6: Verify and commit**

Run:

```bash
.venv/bin/pytest tests/packaging/test_metadata.py -q
desktop-file-validate data/com.devruby.warpcontrol.desktop
appstreamcli validate --no-net data/com.devruby.warpcontrol.metainfo.xml
```

Expected: PASS. Commit: `ci: verify native packages across supported Linux families`.

### Task 6: x86_64 and arm64 AppImage CI

**Files:**
- Modify: `.github/workflows/packages.yml`
- Modify: `tests/packaging/test_appimage.py`

- [ ] **Step 1: Write failing CI assertions**

Require `ubuntu-22.04`/x86_64 and `ubuntu-22.04-arm`/aarch64, checksum verification before executing appimagetool, extraction, forbidden-file scan and smoke test.

- [ ] **Step 2: Prove failure**

Run: `.venv/bin/pytest tests/packaging/test_appimage.py -q`

Expected: FAIL because AppImage jobs are absent.

- [ ] **Step 3: Add native-architecture jobs**

Install PyInstaller/GTK dependencies, download the pinned architecture-specific AppImageKit tool, validate it against `packaging/appimage/appimagetool.sha256`, then call `scripts/build-appimage.sh`. GitHub documents both runner labels; if arm64 cannot be scheduled, fail visibly rather than omit the artifact.

- [ ] **Step 4: Inspect and upload**

Reject extracted paths/content matching:

```text
usr/libexec/warp-control
usr/share/polkit-1
warp-cli
warp-svc
dnf
apt-get
pacman
```

Upload `appimage-x86_64` and `appimage-aarch64`.

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/pytest tests/packaging/test_appimage.py tests/packaging/test_metadata.py -q`

Expected: PASS. Commit: `ci: build AppImages on native Linux architectures`.

### Task 7: Complete tag-gated releases

**Files:**
- Create: `.github/workflows/release.yml`
- Create: `scripts/verify-release.sh`
- Create: `tests/packaging/test_release_workflow.py`
- Modify: `.github/workflows/packages.yml`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Write failing release tests**

Require a tag-only `v*` trigger, `contents: write` only on publication, equality across tag/release.env/pyproject/RPM/DEB/PKGBUILD, every artifact family and `SHA256SUMS`, with publication dependent on all builds.

- [ ] **Step 2: Prove failure**

Run: `.venv/bin/pytest tests/packaging/test_release_workflow.py -q`

Expected: FAIL because workflow/verifier are absent.

- [ ] **Step 3: Implement release verification**

`scripts/verify-release.sh TAG RELEASE_DIR` validates strict `vMAJOR.MINOR.PATCH`, all metadata versions, required RPM/DEB/Arch/AppImage/source artifacts, regular-file/no-symlink inputs and unique basenames; it emits sorted `SHA256SUMS` under `LC_ALL=C`.

- [ ] **Step 4: Make package builds reusable and implement publication**

Add `workflow_call` to `packages.yml` without removing push/pull-request triggers. `release.yml` has a `packages` job using `./.github/workflows/packages.yml`; a `publish` job declares `needs: packages`, downloads all artifacts from the same caller run into isolated directories, validates/flattens them and publishes with the preinstalled GitHub CLI:

```yaml
jobs:
  packages:
    uses: ./.github/workflows/packages.yml
  publish:
    needs: packages
    permissions:
      contents: write
```

Publication command:

```bash
gh release create "$GITHUB_REF_NAME" release/* \
  --verify-tag --title "WARP Control $GITHUB_REF_NAME" --generate-notes
```

Set `GH_TOKEN: ${{ github.token }}` only for that step. CI never creates/pushes a tag or alters a package repository.

- [ ] **Step 5: Verify and commit**

Run:

```bash
.venv/bin/pytest tests/packaging/test_release_workflow.py -q
bash -n scripts/verify-release.sh
```

Expected: PASS including missing, duplicate and tampered fixtures. Commit: `ci: publish complete checksummed Linux releases`.

### Task 8: Documentation and final release gate

**Files:**
- Modify: `README.md`
- Modify: `docs/INSTALL.md`
- Modify: `docs/SUPPORT.md`
- Modify: `CHANGELOG.md`
- Modify: `PROJECT_CONTEXT.md`
- Modify: `NEXT_STEPS.md`
- Modify: `tests/test_documentation.py`

- [ ] **Step 1: Write failing documentation contracts**

Require all six screenshot paths, a four-row RPM/DEB/Arch/AppImage download table, both AppImage architectures, official/community/portable labels, checksum commands and explicit Windows/macOS exclusion.

- [ ] **Step 2: Prove failure**

Run: `.venv/bin/pytest tests/test_documentation.py -q`

Expected: FAIL because screenshots exist but artifact/AppImage instructions do not.

- [ ] **Step 3: Update user documentation**

Keep all six screenshots. Add release filenames, `sha256sum -c SHA256SUMS`, native install commands and AppImage local integration. State that AppImage broadens WARP Control coverage but does not make Cloudflare WARP officially supported outside Cloudflare's matrix.

- [ ] **Step 4: Correct project context**

Remove the stale monolithic-script statement. Record verified matrices/artifact names. `NEXT_STEPS.md` contains only remote operations still requiring authorization (push, CI observation, tag/release).

- [ ] **Step 5: Run the complete local gate**

```bash
PYTHONPATH=src .venv/bin/pytest -q
.venv/bin/ruff check .
PYTHONPATH=src .venv/bin/python -m warp_control --smoke-test
bash -n scripts/*.sh packaging/appimage/AppRun
desktop-file-validate data/com.devruby.warpcontrol.desktop packaging/appimage/com.devruby.warpcontrol.desktop
appstreamcli validate --no-net data/com.devruby.warpcontrol.metainfo.xml
git diff --check
```

Expected: every command exits 0. The existing PyGObject deprecation warning is permitted; failures are not.

- [ ] **Step 6: Bounded independent review and commit**

Delegate one workflow or package family per Claude Haiku prompt, independently reproduce every reported issue, then commit: `docs: document complete Linux release coverage`.

## Execution order and remote boundary

Tasks 1–4 yield a local portable path. Tasks 5–7 establish native matrices and publishing. Task 8 closes documentation/context. Do not push a tag until local tests pass and GitHub Actions passes once on `main`; `git push`, tag creation and GitHub Release publication remain explicit external actions requiring confirmation.
