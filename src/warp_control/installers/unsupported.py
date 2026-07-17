from .detector import Architecture, Distribution, SystemInfo
from .models import InstallAction, InstallPlan


_ARCH_FAMILY = (Distribution.ARCH, Distribution.MANJARO, Distribution.ENDEAVOUROS)


def unsupported_plan(system: SystemInfo) -> InstallPlan:
    if (
        system.distribution in _ARCH_FAMILY
        and system.architecture in (Architecture.AMD64, Architecture.ARM64)
    ):
        return InstallPlan(
            False,
            "Soporte experimental: Cloudflare no publica un paquete oficial para Arch.",
            (InstallAction.SHOW_COMMUNITY_INSTRUCTIONS,),
        )
    return InstallPlan(
        False,
        "Esta distribución, versión o arquitectura no está validada.",
        (InstallAction.SHOW_MANUAL_INSTRUCTIONS,),
    )
