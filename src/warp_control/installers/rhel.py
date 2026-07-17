from .detector import Architecture, SystemInfo
from .models import InstallAction, InstallPlan


_OFFICIAL_ACTIONS = (
    InstallAction.INSTALL_EPEL,
    InstallAction.ADD_CLOUDFLARE_REPOSITORY,
    InstallAction.REFRESH_PACKAGE_METADATA,
    InstallAction.INSTALL_CLOUDFLARE_WARP,
    InstallAction.ENABLE_WARP_SERVICE,
)


def rhel_plan(system: SystemInfo) -> InstallPlan:
    major_version = system.version.split(".", 1)[0] if system.version else ""
    if (
        system.architecture in (Architecture.AMD64, Architecture.ARM64)
        and major_version in ("9", "10")
    ):
        return InstallPlan(True, None, _OFFICIAL_ACTIONS)
    return InstallPlan(
        False,
        "Esta versión o arquitectura de RHEL no está validada.",
        (InstallAction.SHOW_MANUAL_INSTRUCTIONS,),
    )
