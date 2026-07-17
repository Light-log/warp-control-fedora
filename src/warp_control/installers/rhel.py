import re

from .detector import Architecture, Distribution, SystemInfo
from .models import InstallAction, InstallPlan


_OFFICIAL_ACTIONS = (
    InstallAction.INSTALL_EPEL,
    InstallAction.ADD_CLOUDFLARE_REPOSITORY,
    InstallAction.REFRESH_PACKAGE_METADATA,
    InstallAction.INSTALL_CLOUDFLARE_WARP,
    InstallAction.ENABLE_WARP_SERVICE,
)
_SUPPORTED_VERSION = re.compile(r"^(?:9|10)(?:\.[0-9]+)*$")


def rhel_plan(system: SystemInfo) -> InstallPlan:
    if system.distribution is not Distribution.RHEL:
        return InstallPlan(
            False,
            "El plan de RHEL recibió otra distribución; no se realizará ninguna acción.",
            (),
        )
    if (
        system.architecture in (Architecture.AMD64, Architecture.ARM64)
        and system.version is not None
        and _SUPPORTED_VERSION.fullmatch(system.version)
    ):
        return InstallPlan(True, None, _OFFICIAL_ACTIONS)
    return InstallPlan(
        False,
        "Esta versión o arquitectura de RHEL no está validada.",
        (InstallAction.SHOW_MANUAL_INSTRUCTIONS,),
    )
