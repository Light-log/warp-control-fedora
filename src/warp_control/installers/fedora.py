from .detector import Architecture, SystemInfo
from .models import InstallAction, InstallPlan


_SUPPORTED_VERSIONS = frozenset(("43", "44"))
_OFFICIAL_ACTIONS = (
    InstallAction.ADD_CLOUDFLARE_REPOSITORY,
    InstallAction.REFRESH_PACKAGE_METADATA,
    InstallAction.INSTALL_CLOUDFLARE_WARP,
    InstallAction.ENABLE_WARP_SERVICE,
)


def fedora_plan(system: SystemInfo) -> InstallPlan:
    if (
        system.architecture in (Architecture.AMD64, Architecture.ARM64)
        and system.version in _SUPPORTED_VERSIONS
    ):
        return InstallPlan(True, None, _OFFICIAL_ACTIONS)
    return InstallPlan(
        False,
        "Esta versión o arquitectura de Fedora no está validada.",
        (InstallAction.SHOW_MANUAL_INSTRUCTIONS,),
    )
