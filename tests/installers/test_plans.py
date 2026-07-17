from dataclasses import FrozenInstanceError

import pytest

from warp_control.installers import installation_plan
from warp_control.installers.detector import Architecture, Distribution, SystemInfo
from warp_control.installers.models import InstallAction, OfficialSource


PRIVILEGED_ACTIONS = {
    InstallAction.ADD_CLOUDFLARE_REPOSITORY,
    InstallAction.INSTALL_EPEL,
    InstallAction.REFRESH_PACKAGE_METADATA,
    InstallAction.INSTALL_CLOUDFLARE_WARP,
    InstallAction.ENABLE_WARP_SERVICE,
}


def system(distribution, version, codename=None, arch=Architecture.AMD64):
    return SystemInfo(distribution, version, codename, arch)


@pytest.mark.parametrize("version", ["43", "44"])
@pytest.mark.parametrize("arch", [Architecture.AMD64, Architecture.ARM64])
def test_supported_fedora_plan(version, arch):
    plan = installation_plan(system(Distribution.FEDORA, version, arch=arch))

    assert plan.supported is True
    assert plan.warning is None
    assert plan.actions == (
        InstallAction.ADD_CLOUDFLARE_REPOSITORY,
        InstallAction.REFRESH_PACKAGE_METADATA,
        InstallAction.INSTALL_CLOUDFLARE_WARP,
        InstallAction.ENABLE_WARP_SERVICE,
    )


@pytest.mark.parametrize(
    ("version", "codename"),
    [("22.04", "jammy"), ("24.04", "noble"), ("26.04", "resolute")],
)
def test_supported_ubuntu_plan_requires_matching_version_and_codename(version, codename):
    plan = installation_plan(system(Distribution.UBUNTU, version, codename))

    assert plan.supported is True
    assert plan.actions == (
        InstallAction.ADD_CLOUDFLARE_REPOSITORY,
        InstallAction.REFRESH_PACKAGE_METADATA,
        InstallAction.INSTALL_CLOUDFLARE_WARP,
        InstallAction.ENABLE_WARP_SERVICE,
    )


@pytest.mark.parametrize("version,codename", [("12", "bookworm"), ("13", "trixie")])
def test_supported_debian_plan(version, codename):
    plan = installation_plan(system(Distribution.DEBIAN, version, codename))
    assert plan.supported is True
    assert plan.actions[0] is InstallAction.ADD_CLOUDFLARE_REPOSITORY


@pytest.mark.parametrize("version", ["9", "9.6", "10", "10.1"])
def test_supported_rhel_plan_includes_epel(version):
    plan = installation_plan(system(Distribution.RHEL, version))

    assert plan.supported is True
    assert plan.actions == (
        InstallAction.INSTALL_EPEL,
        InstallAction.ADD_CLOUDFLARE_REPOSITORY,
        InstallAction.REFRESH_PACKAGE_METADATA,
        InstallAction.INSTALL_CLOUDFLARE_WARP,
        InstallAction.ENABLE_WARP_SERVICE,
    )


@pytest.mark.parametrize(
    "distribution",
    [Distribution.ARCH, Distribution.MANJARO, Distribution.ENDEAVOUROS],
)
def test_arch_family_is_experimental_and_instructions_only(distribution):
    plan = installation_plan(system(distribution, None))

    assert plan.supported is False
    assert plan.actions == (InstallAction.SHOW_COMMUNITY_INSTRUCTIONS,)
    assert "experimental" in plan.warning.lower()
    assert not PRIVILEGED_ACTIONS.intersection(plan.actions)


@pytest.mark.parametrize(
    "candidate",
    [
        system(Distribution.FEDORA, "42"),
        system(Distribution.FEDORA, "rawhide"),
        system(Distribution.UBUNTU, "24.04", "jammy"),
        system(Distribution.UBUNTU, "25.10", "questing"),
        system(Distribution.DEBIAN, "11", "bullseye"),
        system(Distribution.DEBIAN, "13", "bookworm"),
        system(Distribution.RHEL, "8.10"),
        system(Distribution.UNKNOWN, "1"),
        system(Distribution.FEDORA, "44", arch=Architecture.UNKNOWN),
    ],
)
def test_unknown_or_unsupported_system_has_zero_privileged_actions(candidate):
    plan = installation_plan(candidate)

    assert plan.supported is False
    assert plan.actions == (InstallAction.SHOW_MANUAL_INSTRUCTIONS,)
    assert not PRIVILEGED_ACTIONS.intersection(plan.actions)


def test_install_plan_is_immutable_and_actions_are_closed_enum_members():
    plan = installation_plan(system(Distribution.FEDORA, "44"))

    with pytest.raises(FrozenInstanceError):
        plan.supported = False
    assert all(isinstance(action, InstallAction) for action in plan.actions)
    assert not hasattr(plan, "command")
    assert not hasattr(plan, "url")


def test_upstream_sources_are_a_closed_allowlist():
    assert {source.value for source in OfficialSource} == {
        "https://pkg.cloudflareclient.com/cloudflare-warp-ascii.repo",
        "https://pkg.cloudflareclient.com/pubkey.gpg",
        "https://pkg.cloudflareclient.com/",
    }
