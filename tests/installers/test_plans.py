from dataclasses import FrozenInstanceError

import pytest

from warp_control.installers import installation_plan
from warp_control.installers.debian import debian_plan
from warp_control.installers.detector import Architecture, Distribution, SystemInfo
from warp_control.installers.fedora import fedora_plan
from warp_control.installers.models import (
    PRIVILEGED_ACTIONS,
    InstallAction,
    InstallPlan,
    OfficialSource,
)
from warp_control.installers.rhel import rhel_plan


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


@pytest.mark.parametrize("version", ["9", "9.6", "9.0.1", "10", "10.1"])
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
    "version",
    ["9.", "10.", "9.evil", "10.1x", "09", "10-1", " 9", "9 ", "9..1"],
)
def test_rhel_plan_rejects_malformed_version_ids(version):
    plan = rhel_plan(system(Distribution.RHEL, version))

    assert plan.supported is False
    assert not PRIVILEGED_ACTIONS.intersection(plan.actions)


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


def test_install_plan_copies_action_sequences_to_an_immutable_tuple():
    supplied = [InstallAction.SHOW_MANUAL_INSTRUCTIONS]

    plan = InstallPlan(False, "No soportado", supplied)
    supplied.append(InstallAction.SHOW_COMMUNITY_INSTRUCTIONS)

    assert plan.actions == (InstallAction.SHOW_MANUAL_INSTRUCTIONS,)
    assert isinstance(plan.actions, tuple)


@pytest.mark.parametrize("invalid", ["install_epel", object(), 1, None])
def test_install_plan_rejects_non_enum_actions(invalid):
    with pytest.raises((TypeError, ValueError)):
        InstallPlan(True, None, (invalid,))


@pytest.mark.parametrize("action", sorted(PRIVILEGED_ACTIONS, key=lambda item: item.value))
def test_unsupported_install_plan_rejects_every_privileged_action(action):
    with pytest.raises(ValueError, match="privilegiada"):
        InstallPlan(False, "No soportado", (action,))


@pytest.mark.parametrize(
    "candidate",
    [
        system(Distribution.UNKNOWN, "44"),
        system(Distribution.RHEL, "44"),
        system(Distribution.MANJARO, "44"),
    ],
)
def test_fedora_planner_rejects_valid_version_from_other_distribution(candidate):
    plan = fedora_plan(candidate)

    assert plan.supported is False
    assert plan.actions == ()


@pytest.mark.parametrize(
    "candidate",
    [
        system(Distribution.UNKNOWN, "13", "trixie"),
        system(Distribution.FEDORA, "13", "trixie"),
        system(Distribution.MANJARO, "13", "trixie"),
    ],
)
def test_debian_planner_rejects_valid_debian_release_from_other_distribution(candidate):
    plan = debian_plan(candidate)

    assert plan.supported is False
    assert plan.actions == ()


@pytest.mark.parametrize(
    "candidate",
    [
        system(Distribution.DEBIAN, "24.04", "noble"),
        system(Distribution.UBUNTU, "13", "trixie"),
    ],
)
def test_debian_planner_does_not_mix_ubuntu_and_debian_release_maps(candidate):
    plan = debian_plan(candidate)

    assert plan.supported is False
    assert plan.actions == (InstallAction.SHOW_MANUAL_INSTRUCTIONS,)


@pytest.mark.parametrize(
    "candidate",
    [
        system(Distribution.UNKNOWN, "10"),
        system(Distribution.FEDORA, "10"),
        system(Distribution.ENDEAVOUROS, "10"),
    ],
)
def test_rhel_planner_rejects_valid_version_from_other_distribution(candidate):
    plan = rhel_plan(candidate)

    assert plan.supported is False
    assert plan.actions == ()
