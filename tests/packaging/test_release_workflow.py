from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).parents[2]
VERIFY_RELEASE = ROOT / "scripts" / "verify-release.sh"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
PACKAGES_WORKFLOW = ROOT / ".github" / "workflows" / "packages.yml"
RELEASE_ENV = (ROOT / "packaging/release.env").read_text(encoding="utf-8")
VERSION_MATCHES = re.findall(r"^VERSION=([^=]+)$", RELEASE_ENV, flags=re.MULTILINE)
assert len(VERSION_MATCHES) == 1
VERSION = VERSION_MATCHES[0]
assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", VERSION)


def _required_artifacts(version: str = VERSION) -> list[str]:
    return [
        f"warp-control-{version}.tar.gz",
        f"warp-control-{version}-1.fc43.noarch.rpm",
        f"warp-control-{version}-1.fc44.noarch.rpm",
        f"warp-control-{version}-1.el9.noarch.rpm",
        f"warp-control-{version}-1.el10.noarch.rpm",
        f"warp-control_{version}-1_all-ubuntu2204.deb",
        f"warp-control_{version}-1_all-ubuntu2404.deb",
        f"warp-control_{version}-1_all-ubuntu2604.deb",
        f"warp-control_{version}-1_all-debian12.deb",
        f"warp-control_{version}-1_all-debian13.deb",
        f"warp-control-{version}-1-any.pkg.tar.zst",
        f"WARP-Control-{version}-x86_64.AppImage",
        f"WARP-Control-{version}-aarch64.AppImage",
    ]


def _workflow(path: Path) -> dict:
    assert path.is_file(), f"missing workflow: {path}"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _step_runs(job: dict) -> str:
    return "\n".join(step.get("run", "") for step in job.get("steps", []))


def _fixture_repo(tmp_path: Path) -> tuple[Path, Path]:
    assert VERIFY_RELEASE.is_file(), "release verifier must exist"
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "packaging/rpm").mkdir(parents=True)
    (repo / "packaging/arch").mkdir(parents=True)
    (repo / "debian").mkdir()
    shutil.copy2(VERIFY_RELEASE, repo / "scripts/verify-release.sh")
    (repo / "packaging/release.env").write_text(
        f"VERSION={VERSION}\nSOURCE_DATE_EPOCH=1784678400\n", encoding="utf-8"
    )
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "warp-control"\nversion = "{VERSION}"\n',
        encoding="utf-8",
    )
    (repo / "packaging/rpm/warp-control.spec").write_text(
        f"Name: warp-control\nVersion: {VERSION}\nRelease: 1%{{?dist}}\n",
        encoding="utf-8",
    )
    (repo / "debian/changelog").write_text(
        f"warp-control ({VERSION}-1) unstable; urgency=medium\n", encoding="utf-8"
    )
    (repo / "packaging/arch/PKGBUILD").write_text(
        f"pkgname=warp-control\npkgver={VERSION}\npkgrel=1\n", encoding="utf-8"
    )
    release_dir = repo / "downloads"
    release_dir.mkdir()
    for index, name in enumerate(_required_artifacts()):
        artifact_dir = release_dir / f"artifact-{index:02d}"
        artifact_dir.mkdir()
        (artifact_dir / name).write_bytes(f"fixture:{name}\n".encode())
    return repo, release_dir


def _verify(repo: Path, release_dir: Path, tag: str = f"v{VERSION}") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(repo / "scripts/verify-release.sh"), tag, str(release_dir)],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )


def test_release_workflow_is_tag_only_and_calls_package_workflow() -> None:
    release = _workflow(RELEASE_WORKFLOW)
    packages = _workflow(PACKAGES_WORKFLOW)
    release_on = release.get("on", release.get(True))
    packages_on = packages.get("on", packages.get(True))

    assert release_on == {"push": {"tags": ["v*"]}}
    assert "workflow_call" in packages_on
    assert packages_on["push"] == {"branches": ["**"]}
    assert "pull_request" in packages_on
    assert release["jobs"]["packages"] == {
        "uses": "./.github/workflows/packages.yml"
    }


def test_only_publish_job_can_write_contents_and_waits_for_all_packages() -> None:
    workflow = _workflow(RELEASE_WORKFLOW)

    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["publish"]["needs"] == "packages"
    assert workflow["jobs"]["publish"]["permissions"] == {"contents": "write"}
    for name, job in workflow["jobs"].items():
        if name != "publish":
            assert job.get("permissions", {}).get("contents") != "write"


def test_publication_downloads_same_run_artifacts_in_isolation_then_verifies() -> None:
    publish = _workflow(RELEASE_WORKFLOW)["jobs"]["publish"]
    text = yaml.safe_dump(publish, sort_keys=False)
    runs = _step_runs(publish)

    assert "actions/download-artifact@v4" in text
    assert "path: downloads" in text
    assert "merge-multiple: false" in text
    assert "run-id:" not in text
    assert "github-token:" not in text
    assert "repository:" not in text
    assert 'scripts/verify-release.sh "$GITHUB_REF_NAME" release' in runs
    assert "release/" in runs
    assert "SHA256SUMS" in runs
    assert "gh release create \"$GITHUB_REF_NAME\" release/*" in runs
    assert "--verify-tag" in runs
    assert "GH_TOKEN: ${{ github.token }}" in text


def test_publication_renames_isolated_debs_without_changing_native_packages() -> None:
    jobs = _workflow(PACKAGES_WORKFLOW)["jobs"]
    publish_text = _step_runs(_workflow(RELEASE_WORKFLOW)["jobs"]["publish"])

    assert "build/warp-control_*_all.deb" in yaml.safe_dump(jobs["deb"])
    assert "package/warp-control_*_all.deb" in yaml.safe_dump(jobs["deb-install"])
    for target in ("ubuntu2204", "ubuntu2404", "ubuntu2604", "debian12", "debian13"):
        assert target in publish_text
    assert "downloads/deb-$target/warp-control_*_all.deb" in publish_text
    assert "_all-$target.deb" in publish_text
    assert "refusing to overwrite" in publish_text


def test_verifier_accepts_exact_artifacts_and_emits_sorted_checksums(tmp_path: Path) -> None:
    repo, release_dir = _fixture_repo(tmp_path)

    result = _verify(repo, release_dir)

    assert result.returncode == 0, result.stderr
    manifest = (release_dir / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    assert [line.split("  ", 1)[1] for line in manifest] == sorted(
        _required_artifacts(), key=os.fsencode
    )
    for line in manifest:
        digest, name = line.split("  ", 1)
        artifact = next(release_dir.rglob(name))
        assert digest == hashlib.sha256(artifact.read_bytes()).hexdigest()


def test_verifier_reads_only_the_current_debian_changelog_stanza(tmp_path: Path) -> None:
    repo, release_dir = _fixture_repo(tmp_path)
    with (repo / "debian/changelog").open("a", encoding="utf-8") as changelog:
        changelog.write(
            "\nwarp-control (1.9.0-4) unstable; urgency=medium\n"
            "\n  * Historical release.\n"
        )

    result = _verify(repo, release_dir)

    assert result.returncode == 0, result.stderr


def test_verifier_rejects_missing_artifact(tmp_path: Path) -> None:
    repo, release_dir = _fixture_repo(tmp_path)
    next(release_dir.rglob(_required_artifacts()[0])).unlink()

    result = _verify(repo, release_dir)

    assert result.returncode != 0
    assert "missing" in result.stderr.lower()


def test_verifier_rejects_duplicate_basename(tmp_path: Path) -> None:
    repo, release_dir = _fixture_repo(tmp_path)
    original = next(release_dir.rglob(_required_artifacts()[0]))
    duplicate_dir = release_dir / "duplicate"
    duplicate_dir.mkdir()
    shutil.copy2(original, duplicate_dir / original.name)

    result = _verify(repo, release_dir)

    assert result.returncode != 0
    assert "duplicate" in result.stderr.lower()


def test_verifier_rejects_artifact_tampered_after_manifest(tmp_path: Path) -> None:
    repo, release_dir = _fixture_repo(tmp_path)
    assert _verify(repo, release_dir).returncode == 0
    artifact = next(release_dir.rglob(_required_artifacts()[-1]))
    artifact.write_bytes(b"tampered\n")

    result = _verify(repo, release_dir)

    assert result.returncode != 0
    assert "checksum" in result.stderr.lower()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("bad-tag", "tag"),
        ("bad-version", "version"),
        ("symlink", "symlink"),
        ("unexpected", "unexpected"),
    ],
)
def test_verifier_rejects_invalid_release_inputs(
    tmp_path: Path, mutation: str, message: str
) -> None:
    repo, release_dir = _fixture_repo(tmp_path)
    tag = f"v{VERSION}"
    if mutation == "bad-tag":
        tag = VERSION
    elif mutation == "bad-version":
        (repo / "pyproject.toml").write_text(
            '[project]\nname = "warp-control"\nversion = "9.9.9"\n',
            encoding="utf-8",
        )
    elif mutation == "symlink":
        (release_dir / "unsafe-link").symlink_to(next(release_dir.rglob("*.rpm")))
    elif mutation == "unexpected":
        (release_dir / "artifact-extra.bin").write_bytes(b"extra\n")

    result = _verify(repo, release_dir, tag)

    assert result.returncode != 0
    assert message in result.stderr.lower()
