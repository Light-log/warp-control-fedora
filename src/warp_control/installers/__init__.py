"""Fail-closed installation planning for supported Linux distributions."""

from .debian import debian_plan
from .detector import Distribution, SystemInfo
from .fedora import fedora_plan
from .models import InstallPlan
from .rhel import rhel_plan
from .unsupported import unsupported_plan


def installation_plan(system: SystemInfo) -> InstallPlan:
    """Return a declarative plan without executing or constructing commands."""

    if system.distribution is Distribution.FEDORA:
        return fedora_plan(system)
    if system.distribution in (Distribution.UBUNTU, Distribution.DEBIAN):
        return debian_plan(system)
    if system.distribution is Distribution.RHEL:
        return rhel_plan(system)
    return unsupported_plan(system)


__all__ = ["InstallPlan", "installation_plan"]
