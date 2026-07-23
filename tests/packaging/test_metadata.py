from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[2]
CONTROL = ROOT / "debian/control"
INSTALL = ROOT / "debian/warp-control.install"
PKGBUILD = ROOT / "packaging/arch/PKGBUILD"
RELEASE_ENV = ROOT / "packaging/release.env"
PACKAGES_WORKFLOW = ROOT / ".github/workflows/packages.yml"
QUALITY_WORKFLOW = ROOT / ".github/workflows/quality.yml"
RPM_SPEC = ROOT / "packaging/rpm/warp-control.spec"


def _workflow_text() -> str:
    return PACKAGES_WORKFLOW.read_text(encoding="utf-8")


def _workflow_jobs() -> dict:
    data = yaml.safe_load(_workflow_text())
    return data["jobs"]


def _job_text(job: dict) -> str:
    return yaml.safe_dump(job)


def _all_step_runs(job: dict) -> str:
    return "\n".join(
        step.get("run", "") for step in job.get("steps", []) if isinstance(step, dict)
    )


def _matrix_includes(job: dict) -> list[dict]:
    return job["strategy"]["matrix"]["include"]


def _paragraphs(text: str) -> list[dict[str, str]]:
    paragraphs: list[dict[str, str]] = []
    for block in text.strip().split("\n\n"):
        fields: dict[str, str] = {}
        current = ""
        for line in block.splitlines():
            if line.startswith((" ", "\t")):
                fields[current] += "\n" + line[1:]
                continue
            current, value = line.split(":", 1)
            fields[current] = value.strip()
        paragraphs.append(fields)
    return paragraphs


def _shell_array(text: str, name: str) -> set[str]:
    match = re.search(rf"^{name}=\((.*?)\)$", text, flags=re.MULTILINE | re.DOTALL)
    assert match is not None, name
    return set(re.findall(r"['\"]([^'\"]+)['\"]", match.group(1)))


def test_debian_control_is_architecture_independent_and_native() -> None:
    source, binary = _paragraphs(CONTROL.read_text(encoding="utf-8"))

    assert source["Source"] == "warp-control"
    assert source["Homepage"] == "https://github.com/Light-log/warp-control-fedora"
    assert binary["Package"] == "warp-control"
    assert binary["Architecture"] == "all"
    build_depends = source["Build-Depends"]
    for dependency in (
        "debhelper-compat (= 13)",
        "dh-sequence-python3",
        "pybuild-plugin-pyproject",
        "python3-all",
        "python3-setuptools",
        "python3-wheel",
        "python3-yaml",
    ):
        assert dependency in build_depends

    depends = binary["Depends"]
    for dependency in (
        "${python3:Depends}",
        "${misc:Depends}",
        "python3-gi",
        "gir1.2-gtk-3.0",
        "gir1.2-ayatanaappindicator3-0.1",
        "python3-idna",
        "pkexec",
        "polkitd",
        "apt",
        "curl",
        "gnupg",
        "systemd",
    ):
        assert dependency in depends
    assert "policykit-1" not in depends


def test_debian_rules_uses_pybuild_pyproject() -> None:
    rules = (ROOT / "debian/rules").read_text(encoding="utf-8")

    assert rules.startswith("#!/usr/bin/make -f\n")
    assert "PYBUILD_SYSTEM=pyproject" in rules
    assert "dh $@ --with python3 --buildsystem=pybuild" in rules
    assert 'PYTHONPATH=src python3 -m pytest -m "not ui"' in rules
    assert "tests/test_*.py tests/installers tests/services tests/ui" in rules
    assert "tests/packaging" not in rules
    assert "tests/shell" not in rules


def test_native_package_checks_run_application_tests_only() -> None:
    selected = "tests/test_*.py tests/installers tests/services tests/ui"
    rules = (ROOT / "debian/rules").read_text(encoding="utf-8")
    spec = RPM_SPEC.read_text(encoding="utf-8")
    pkgbuild = PKGBUILD.read_text(encoding="utf-8")

    for metadata in (rules, spec, pkgbuild):
        assert selected in metadata
        assert "tests/packaging" not in metadata
        assert "tests/shell" not in metadata


def test_debian_install_manifest_is_explicit() -> None:
    entries = set(INSTALL.read_text(encoding="utf-8").splitlines())

    assert entries == {
        "data/com.devruby.warpcontrol.desktop usr/share/applications/",
        "data/com.devruby.warpcontrol.metainfo.xml usr/share/metainfo/",
        "data/icons/com.devruby.warpcontrol.svg usr/share/icons/hicolor/scalable/apps/",
        "data/com.devruby.warpcontrol.policy usr/share/polkit-1/actions/",
        "libexec/warp-control/install-warp usr/libexec/warp-control/",
        "libexec/warp-control/restart-warp usr/libexec/warp-control/",
    }


def test_arch_package_is_application_only_and_architecture_independent() -> None:
    pkgbuild = PKGBUILD.read_text(encoding="utf-8")

    assert "arch=('any')" in pkgbuild
    assert "url='https://github.com/Light-log/warp-control-fedora'" in pkgbuild
    assert "license=('MIT')" in pkgbuild
    assert _shell_array(pkgbuild, "depends") == {
        "python",
        "python-gobject",
        "gtk3",
        "libayatana-appindicator",
        "python-idna",
    }
    assert "warp-cli" in pkgbuild
    assert "experimental" in pkgbuild.lower()
    assert "optdepends=" not in pkgbuild
    assert "usr/share/applications" in pkgbuild
    assert "usr/share/metainfo" in pkgbuild
    assert "usr/share/icons/hicolor/scalable/apps" in pkgbuild
    assert "usr/libexec" not in pkgbuild
    assert "polkit-1" not in pkgbuild
    assert _shell_array(pkgbuild, "checkdepends") == {"python-pytest", "python-yaml"}


def test_arch_source_is_a_tarball_release() -> None:
    pkgbuild = PKGBUILD.read_text(encoding="utf-8")
    sources = _shell_array(pkgbuild, "source")
    checksums = _shell_array(pkgbuild, "sha256sums")
    makedepends = _shell_array(pkgbuild, "makedepends")

    assert "source_commit=" not in pkgbuild
    assert "git+" not in pkgbuild
    assert len(sources) == 1
    source = next(iter(sources))
    assert "releases/download/v" in source
    assert "$pkgname-$pkgver.tar.gz" in source
    assert len(checksums) == 1
    checksum = next(iter(checksums))
    assert re.fullmatch(r"[a-f0-9]{64}", checksum), f"Expected lowercase 64-char sha256, got {checksum}"
    assert "SKIP" not in checksums
    assert "git" not in makedepends
    assert 'cd "$srcdir/$pkgname-$pkgver"' in pkgbuild or 'cd "$srcdir/warp-control-$pkgver"' in pkgbuild


def test_release_contract_has_one_valid_version_and_epoch() -> None:
    assert RELEASE_ENV.read_text(encoding="utf-8").splitlines() == [
        "VERSION=2.0.0",
        "SOURCE_DATE_EPOCH=1784678400",
    ]


def test_native_packages_never_depend_on_or_install_cloudflare_warp() -> None:
    control = CONTROL.read_text(encoding="utf-8").lower()
    pkgbuild = PKGBUILD.read_text(encoding="utf-8").lower()

    assert "cloudflare-warp" not in control
    assert "cloudflare-warp" not in pkgbuild
    assert not any(
        (ROOT / "debian" / name).exists()
        for name in ("postinst", "preinst", "postrm", "prerm")
    )


def test_debian_metadata_files_are_complete() -> None:
    changelog = (ROOT / "debian/changelog").read_text(encoding="utf-8")
    copyright_text = (ROOT / "debian/copyright").read_text(encoding="utf-8")

    assert changelog.startswith("warp-control (2.0.0-1) unstable; urgency=medium\n")
    assert "Fri, 17 Jul 2026" in changelog
    assert "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/" in copyright_text
    assert "License: MIT" in copyright_text
    assert (ROOT / "debian/source/format").read_text(encoding="utf-8") == "3.0 (quilt)\n"


# --- Task 5: native package build/install matrices ---------------------


def test_workflow_builds_the_deterministic_source_once_and_shares_it() -> None:
    jobs = _workflow_jobs()
    text = _workflow_text()

    assert text.count("build-source-tarball.sh") == 1, (
        "the deterministic source tarball must be built by exactly one shared job"
    )
    source_jobs = [
        job_id for job_id, job in jobs.items() if "build-source-tarball.sh" in _all_step_runs(job)
    ]
    assert len(source_jobs) == 1
    source_job_id = source_jobs[0]
    assert "actions/upload-artifact" in _job_text(jobs[source_job_id])

    for job_id in ("rpm", "deb", "arch"):
        job = jobs[job_id]
        needs = job.get("needs", [])
        needs = [needs] if isinstance(needs, str) else needs
        assert source_job_id in needs, f"{job_id} must depend on the shared source job"
        assert "actions/download-artifact" in _job_text(job), (
            f"{job_id} must download the shared source artifact instead of rebuilding it"
        )


def test_workflow_derives_archive_version_once_from_release_metadata() -> None:
    jobs = _workflow_jobs()
    source_job = jobs["source"]
    source_text = _job_text(source_job)
    workflow_text = _workflow_text()

    assert source_job["outputs"]["version"] == "${{ steps.release.outputs.version }}"
    assert "packaging/release.env" in _all_step_runs(source_job)
    assert 'echo "version=$version" >> "$GITHUB_OUTPUT"' in _all_step_runs(source_job)
    assert "dist/warp-control-${{ steps.release.outputs.version }}.tar.gz" in source_text
    assert "needs.source.outputs.version" in workflow_text
    assert "2.0.0" not in workflow_text


def test_workflow_builds_rpm_across_fedora_and_el_targets() -> None:
    jobs = _workflow_jobs()
    rpm_job = jobs["rpm"]
    targets = _matrix_includes(rpm_job)

    assert rpm_job["container"] == "${{ matrix.container }}"
    assert len(targets) == 4
    assert {(target["container"], target["dist_tag"]) for target in targets} == {
        ("fedora:43", "fc43"),
        ("fedora:44", "fc44"),
        ("rockylinux/rockylinux:9", "el9"),
        ("rockylinux/rockylinux:10", "el10"),
    }


def test_workflow_enables_epel_for_el_targets_only() -> None:
    jobs = _workflow_jobs()
    for job_id in ("rpm", "rpm-install"):
        rpm_job = jobs[job_id]
        epel_steps = [step for step in rpm_job["steps"] if "epel-release" in step.get("run", "")]

        assert len(epel_steps) == 1
        assert epel_steps[0]["if"] == "matrix.family == 'el'"
        assert {
            target["major"] for target in _matrix_includes(rpm_job) if target["family"] == "el"
        } == {9, 10}


def test_workflow_enables_crb_before_epel_for_el_builds_and_installs() -> None:
    jobs = _workflow_jobs()

    for job_id in ("rpm", "rpm-install"):
        steps = jobs[job_id]["steps"]
        crb_indexes = [index for index, step in enumerate(steps) if "config-manager" in step.get("run", "")]
        epel_indexes = [index for index, step in enumerate(steps) if "epel-release" in step.get("run", "")]
        assert len(crb_indexes) == len(epel_indexes) == 1
        assert crb_indexes[0] < epel_indexes[0]
        crb_step = steps[crb_indexes[0]]
        assert crb_step["if"] == "matrix.family == 'el'"
        assert "dnf-plugins-core" in crb_step["run"]
        assert "--set-enabled crb" in crb_step["run"]


def test_workflow_does_not_reuse_a_fedora_rpm_on_el_targets() -> None:
    jobs = _workflow_jobs()
    rpm_job = jobs["rpm"]
    run_text = _all_step_runs(rpm_job)

    assert run_text.count("rpmbuild -ba") == 1
    assert '--define "dist .${{ matrix.dist_tag }}"' in run_text
    assert "*.${{ matrix.dist_tag }}.noarch.rpm" in _job_text(rpm_job)
    assert len({target["dist_tag"] for target in _matrix_includes(rpm_job)}) == 4


def test_workflow_installs_the_wheel_backend_for_every_rpm_target() -> None:
    rpm_job = _workflow_jobs()["rpm"]
    requirement_steps = [
        step for step in rpm_job["steps"] if step.get("name") == "Install RPM build requirements"
    ]

    assert len(requirement_steps) == 1
    assert "python3-wheel" in requirement_steps[0]["run"]


def test_workflow_installs_and_smoke_tests_every_built_rpm() -> None:
    jobs = _workflow_jobs()
    build_job = jobs["rpm"]
    install_job = jobs["rpm-install"]
    run_text = _all_step_runs(install_job)

    assert install_job["container"] == "${{ matrix.container }}"
    assert install_job["needs"] == "rpm"
    assert _matrix_includes(install_job) == _matrix_includes(build_job)
    assert len(_matrix_includes(install_job)) == 4
    assert "name: rpm-${{ matrix.target }}" in _job_text(install_job)
    assert run_text.count("/usr/bin/warp-control --smoke-test") == 1
    assert "dnf -y install package/warp-control-*.${{ matrix.dist_tag }}.noarch.rpm" in run_text


def test_workflow_builds_deb_across_ubuntu_and_debian_bases() -> None:
    jobs = _workflow_jobs()
    deb_job = jobs["deb"]
    targets = _matrix_includes(deb_job)

    assert deb_job["container"] == "${{ matrix.container }}"
    assert len(targets) == 5
    assert {target["container"] for target in targets} == {
        "ubuntu:22.04",
        "ubuntu:24.04",
        "ubuntu:26.04",
        "debian:12",
        "debian:13",
    }

    run_text = _all_step_runs(deb_job)
    assert run_text.count("dpkg-buildpackage") == 1
    assert run_text.count("lintian --profile debian --fail-on error") == 1


def test_workflow_deb_builds_from_the_shared_source_tree() -> None:
    deb_job = _workflow_jobs()["deb"]
    run_text = _all_step_runs(deb_job)
    build_steps = [step for step in deb_job["steps"] if "dpkg-buildpackage" in step.get("run", "")]

    assert 'dist/warp-control-$VERSION.tar.gz' in run_text
    assert 'warp-control_$VERSION.orig.tar.gz' in run_text
    assert "tar --extract --gzip" in run_text
    assert len(build_steps) == 1
    assert build_steps[0]["working-directory"] == (
        "build/warp-control-${{ needs.source.outputs.version }}"
    )


def test_workflow_installs_and_smoke_tests_every_built_deb() -> None:
    jobs = _workflow_jobs()
    build_job = jobs["deb"]
    install_job = jobs["deb-install"]
    run_text = _all_step_runs(install_job)

    assert install_job["container"] == "${{ matrix.container }}"
    assert install_job["needs"] == "deb"
    assert _matrix_includes(install_job) == _matrix_includes(build_job)
    assert len(_matrix_includes(install_job)) == 5
    assert "name: deb-${{ matrix.target }}" in _job_text(install_job)
    assert "apt-get install -y ./package/warp-control_*_all.deb" in run_text
    assert run_text.count("/usr/bin/warp-control --smoke-test") == 1


def test_workflow_deb_artifact_names_encode_distro_and_version() -> None:
    jobs = _workflow_jobs()
    deb_job = jobs["deb"]
    targets = [target["target"] for target in _matrix_includes(deb_job)]
    upload_steps = [
        step for step in deb_job["steps"] if step.get("uses", "").startswith("actions/upload-artifact")
    ]

    assert targets == ["ubuntu2204", "ubuntu2404", "ubuntu2604", "debian12", "debian13"]
    assert len(targets) == len(set(targets))
    assert len(upload_steps) == 1
    assert upload_steps[0]["with"]["name"] == "deb-${{ matrix.target }}"


def test_workflow_arch_job_never_modifies_the_committed_pkgbuild() -> None:
    jobs = _workflow_jobs()
    arch_job = jobs.get("arch")
    assert arch_job is not None, "no arch job found"
    run_text = _all_step_runs(arch_job)

    assert "useradd" in run_text, "arch build must run as an unprivileged builder"
    assert "mktemp -d" in run_text, "arch build must stage a temporary PKGBUILD copy"
    committed_references = [
        line.strip() for line in run_text.splitlines() if "packaging/arch" in line
    ]
    assert committed_references == ['cp packaging/arch/PKGBUILD "$build_dir/PKGBUILD"']
    assert not re.search(
        r"(?:sed|tee|makepkg|perl|python|>>?|\|)\s*[^\n]*packaging/arch"
        r"|packaging/arch[^\n]*(?:sed|tee|makepkg|perl|python|>>?|\|)",
        run_text,
    ), "the committed PKGBUILD may only be read into the temporary build directory"
    makepkg_steps = [step for step in arch_job["steps"] if "makepkg" in step.get("run", "")]
    assert len(makepkg_steps) == 1
    assert re.search(r'su builder -c ["].*makepkg', makepkg_steps[0]["run"])


def test_workflow_arch_source_points_at_the_shared_local_tarball() -> None:
    jobs = _workflow_jobs()
    arch_job = jobs.get("arch")
    assert arch_job is not None
    run_text = _all_step_runs(arch_job)

    assert "actions/download-artifact" in _job_text(arch_job)
    assert re.search(r"source=\(.*::\s*file://", run_text) or "source=(\"$pkgname" in run_text, (
        "the temporary PKGBUILD must be rewritten to fetch the deterministic "
        "local tarball rather than downloading a GitHub release"
    )
    assert "releases/download" not in run_text.split("makepkg")[0] or "file://" in run_text


def test_workflow_uploads_the_arch_package_at_the_artifact_root() -> None:
    arch_job = _workflow_jobs()["arch"]
    run_text = _all_step_runs(arch_job)
    upload_steps = [
        step for step in arch_job["steps"] if step.get("uses", "").startswith("actions/upload-artifact")
    ]

    assert len(upload_steps) == 1
    assert upload_steps[0]["with"]["path"] == "dist/arch/warp-control-*.pkg.tar.*"
    assert 'cp "$BUILD_DIR"/warp-control-*.pkg.tar.* dist/arch/' in run_text


def test_workflow_arch_installs_and_smoke_tests_the_built_package() -> None:
    jobs = _workflow_jobs()
    build_job = jobs["arch"]
    install_job = jobs["arch-install"]
    build_run_text = _all_step_runs(build_job)
    install_run_text = _all_step_runs(install_job)

    assert build_job["container"] == "archlinux:latest"
    assert install_job["container"] == "archlinux:latest"
    assert install_job["needs"] == "arch"
    assert "namcap" in build_run_text
    assert "name: arch" in _job_text(install_job)
    assert "pacman -U --noconfirm package/warp-control-*.pkg.tar.*" in install_run_text
    assert "/usr/bin/warp-control --smoke-test" in install_run_text


def test_workflow_required_build_install_and_smoke_steps_are_not_target_limited() -> None:
    jobs = _workflow_jobs()
    required_commands = {
        "rpm": "rpmbuild -ba",
        "rpm-install": "dnf -y install package/warp-control-",
        "deb": "dpkg-buildpackage",
        "deb-install": "apt-get install -y ./package/warp-control_",
        "arch": "makepkg",
        "arch-install": "pacman -U --noconfirm package/warp-control-",
    }

    for job_id, command in required_commands.items():
        matching_steps = [step for step in jobs[job_id]["steps"] if command in step.get("run", "")]
        assert len(matching_steps) == 1, f"{job_id} must run {command!r} exactly once per matrix target"
        assert "if" not in matching_steps[0], f"{job_id} must not skip targets with a step condition"

    for job_id in ("rpm-install", "deb-install", "arch-install"):
        smoke_steps = [
            step
            for step in jobs[job_id]["steps"]
            if "/usr/bin/warp-control --smoke-test" in step.get("run", "")
        ]
        assert len(smoke_steps) == 1
        assert "if" not in smoke_steps[0]


def test_workflow_clean_install_jobs_do_not_checkout_or_install_build_toolchains() -> None:
    jobs = _workflow_jobs()
    forbidden = ("actions/checkout", "rpm-build", "dpkg-buildpackage", "makepkg", "base-devel")

    for job_id in ("rpm-install", "deb-install", "arch-install"):
        job_text = _job_text(jobs[job_id])
        for token in forbidden:
            assert token not in job_text, f"{job_id} clean install job contains {token}"


def test_workflow_clean_install_jobs_run_even_when_a_sibling_build_target_fails() -> None:
    jobs = _workflow_jobs()

    for job_id in ("rpm-install", "deb-install", "arch-install"):
        assert jobs[job_id]["if"] == "${{ always() }}"


def test_yaml_test_dependency_is_declared_for_every_native_builder() -> None:
    control = CONTROL.read_text(encoding="utf-8")
    spec = RPM_SPEC.read_text(encoding="utf-8")
    pkgbuild = PKGBUILD.read_text(encoding="utf-8")
    packages_workflow = _workflow_text()
    quality_workflow = QUALITY_WORKFLOW.read_text(encoding="utf-8")

    assert "BuildRequires:  python3-pyyaml" in spec
    assert "python3-yaml" in _paragraphs(control)[0]["Build-Depends"]
    assert "'python-yaml'" in pkgbuild
    assert "python3-pyyaml" in packages_workflow
    assert "python3-yaml" in packages_workflow
    assert "python-yaml" in packages_workflow
    assert "pip install -e . pytest pyyaml" in quality_workflow
    assert "data/com.robler" not in quality_workflow
    assert "data/com.devruby.warpcontrol.desktop" in quality_workflow
    assert "data/com.devruby.warpcontrol.metainfo.xml" in quality_workflow


def test_legacy_native_build_compatibility_uses_canonical_project_metadata() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    spec = RPM_SPEC.read_text(encoding="utf-8")
    setup_py = (ROOT / "setup.py").read_text(encoding="utf-8")

    assert 'requires = ["setuptools>=59"]' in pyproject
    assert 'project_string("name")' in setup_py
    assert 'project_string("version")' in setup_py
    assert 'project_string("requires-python")' in setup_py
    assert "project_dependencies()" in setup_py
    assert "ast.literal_eval" in setup_py
    assert "if major >= 61" in setup_py
    assert "setup(**legacy_metadata())" in setup_py
    assert "pyproject.toml" in setup_py
    assert "%if 0%{?rhel} == 9" in spec
    assert "%{python3} setup.py build" in spec
    assert "%{python3} setup.py install --skip-build --root %{buildroot}" in spec
    assert "pip install" not in _all_step_runs(_workflow_jobs()["deb"])


def test_packaging_metadata_ends_with_one_newline() -> None:
    for relative in (
        "debian/control",
        "debian/rules",
        "debian/changelog",
        "debian/copyright",
        "debian/source/format",
        "debian/warp-control.install",
        "packaging/arch/PKGBUILD",
    ):
        content = (ROOT / relative).read_bytes()
        assert content.endswith(b"\n"), relative
        assert not content.endswith(b"\n\n"), relative
