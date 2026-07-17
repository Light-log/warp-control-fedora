from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


class InstallAction(str, Enum):
    """Closed action vocabulary consumed by the privileged layer."""

    INSTALL_EPEL = "install_epel"
    ADD_CLOUDFLARE_REPOSITORY = "add_cloudflare_repository"
    REFRESH_PACKAGE_METADATA = "refresh_package_metadata"
    INSTALL_CLOUDFLARE_WARP = "install_cloudflare_warp"
    ENABLE_WARP_SERVICE = "enable_warp_service"
    SHOW_COMMUNITY_INSTRUCTIONS = "show_community_instructions"
    SHOW_MANUAL_INSTRUCTIONS = "show_manual_instructions"


class OfficialSource(str, Enum):
    """Allowlisted upstream locations; plans never accept caller-provided URLs."""

    RPM_REPOSITORY = "https://pkg.cloudflareclient.com/cloudflare-warp-ascii.repo"
    APT_KEY = "https://pkg.cloudflareclient.com/pubkey.gpg"
    APT_REPOSITORY = "https://pkg.cloudflareclient.com/"


@dataclass(frozen=True)
class InstallPlan:
    supported: bool
    warning: Optional[str]
    actions: Tuple[InstallAction, ...]
