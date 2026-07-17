"""Closed Cloudflare repository descriptions and atomic installation."""

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from warp_control.installers import installation_plan
from warp_control.installers.detector import Distribution, SystemInfo
from warp_control.installers.models import OfficialSource


RPM_REPOSITORY_URL = OfficialSource.RPM_REPOSITORY.value
APT_KEY_URL = OfficialSource.APT_KEY.value
APT_REPOSITORY_URL = OfficialSource.APT_REPOSITORY.value
APT_KEYRING = Path("/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg")
APT_SOURCE = Path("/etc/apt/sources.list.d/cloudflare-client.list")
RPM_REPOSITORY = Path("/etc/yum.repos.d/cloudflare-warp.repo")
MAX_DOWNLOAD_BYTES = 256 * 1024
EXPECTED_SIGNING_FINGERPRINT = "C068A2B5771775193CBE1F2F6E2DD2174FA1C3BA"
EXPECTED_SIGNING_UID = "Cloudflare Package Repository <support@cloudflare.com>"
APPROVED_APT_SOURCE_LINES = frozenset(
    "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] "
    f"{APT_REPOSITORY_URL} {codename} main\n"
    for codename in ("jammy", "noble", "resolute", "bookworm", "trixie")
)
_URL = re.compile(r"https?://[^\s'\"<>]+")
_ALLOWED_RPM_URLS = frozenset(
    {
        "https://pkg.cloudflareclient.com/rpm/$releasever",
        APT_KEY_URL,
    }
)


class RepositoryRejected(RuntimeError):
    pass


@dataclass(frozen=True)
class RepositoryConfig:
    family: str
    repository_url: Optional[str] = None
    key_url: Optional[str] = None
    source_line: Optional[str] = None


def repository_config(system: SystemInfo) -> RepositoryConfig:
    plan = installation_plan(system)
    if not plan.supported:
        raise RepositoryRejected("the detected system is not supported")
    if system.distribution in (Distribution.FEDORA, Distribution.RHEL):
        return RepositoryConfig("rpm", repository_url=RPM_REPOSITORY_URL)
    if system.distribution in (Distribution.UBUNTU, Distribution.DEBIAN):
        if not system.codename or not re.fullmatch(r"[a-z][a-z0-9-]{1,31}", system.codename):
            raise RepositoryRejected("invalid APT codename")
        return RepositoryConfig(
            "apt",
            key_url=APT_KEY_URL,
            source_line=(
                "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] "
                f"{APT_REPOSITORY_URL} {system.codename} main\n"
            ),
        )
    raise RepositoryRejected("no official repository exists for this system")


def validate_rpm_repository(contents: bytes) -> None:
    if not contents or len(contents) > MAX_DOWNLOAD_BYTES or b"\x00" in contents:
        raise RepositoryRejected("invalid repository file")
    try:
        text = contents.decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise RepositoryRejected("repository file is not UTF-8") from error
    urls = _URL.findall(text)
    if set(urls) != _ALLOWED_RPM_URLS:
        raise RepositoryRejected("repository file references an unapproved origin")
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not lines or lines[0] != "[cloudflare-warp-stable]":
        raise RepositoryRejected("repository file has an unexpected section")
    values = {}
    for line in lines[1:]:
        if "=" not in line:
            raise RepositoryRejected("repository file has invalid syntax")
        key, value = line.split("=", 1)
        if key in values:
            raise RepositoryRejected("repository file has duplicate settings")
        values[key] = value
    expected = {
        "name": "cloudflare-warp-stable",
        "baseurl": "https://pkg.cloudflareclient.com/rpm/$releasever",
        "enabled": "1",
        "type": "rpm",
        "gpgcheck": "1",
        "gpgkey": APT_KEY_URL,
    }
    if values != expected:
        raise RepositoryRejected("repository file differs from the approved definition")


def validate_signing_key(colon_output: str) -> None:
    """Require exactly one approved primary key; subkey fingerprints are separate."""
    if not isinstance(colon_output, str) or len(colon_output.encode("utf-8")) > MAX_DOWNLOAD_BYTES:
        raise RepositoryRejected("invalid signing key metadata")
    primary_fingerprints = []
    uids = []
    key_kind = None
    primary_count = 0
    for line in colon_output.splitlines():
        fields = line.split(":")
        record = fields[0] if fields else ""
        if record in {"pub", "sub"}:
            key_kind = record
            if record == "pub":
                primary_count += 1
        elif record == "fpr" and len(fields) > 9:
            if key_kind == "pub":
                primary_fingerprints.append(fields[9])
            # A subkey fingerprint is deliberately ignored, never mistaken for primary.
            key_kind = None
        elif record == "uid" and len(fields) > 9:
            uids.append(fields[9])
    if primary_count != 1 or len(primary_fingerprints) != 1:
        raise RepositoryRejected("expected exactly one primary signing key")
    if primary_fingerprints[0] != EXPECTED_SIGNING_FINGERPRINT:
        raise RepositoryRejected("signing key fingerprint is not approved")
    if EXPECTED_SIGNING_UID not in uids:
        raise RepositoryRejected("signing key UID is not approved")


def atomic_write(path: Path, contents: bytes, mode: int = 0o644) -> None:
    path = Path(path)
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as output:
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
