from .detector import Architecture, Distribution, SystemInfo
from .models import InstallAction, InstallPlan


_UBUNTU_RELEASES = {
    "22.04": "jammy",
    "24.04": "noble",
    "26.04": "resolute",
}
_DEBIAN_RELEASES = {"12": "bookworm", "13": "trixie"}
_OFFICIAL_ACTIONS = (
    InstallAction.ADD_CLOUDFLARE_REPOSITORY,
    InstallAction.REFRESH_PACKAGE_METADATA,
    InstallAction.INSTALL_CLOUDFLARE_WARP,
    InstallAction.ENABLE_WARP_SERVICE,
)


def debian_plan(system: SystemInfo) -> InstallPlan:
    releases = _UBUNTU_RELEASES if system.distribution is Distribution.UBUNTU else _DEBIAN_RELEASES
    supported_release = system.version in releases and releases[system.version] == system.codename
    if (
        system.architecture in (Architecture.AMD64, Architecture.ARM64)
        and supported_release
    ):
        return InstallPlan(True, None, _OFFICIAL_ACTIONS)
    return InstallPlan(
        False,
        "Esta versión, codename o arquitectura no está validada.",
        (InstallAction.SHOW_MANUAL_INSTRUCTIONS,),
    )
