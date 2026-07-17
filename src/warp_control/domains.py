import ipaddress
import re
import socket
import unicodedata
from typing import Tuple
from urllib.parse import urlsplit

import idna


_ASCII_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def normalize_host(value: str) -> str:
    """Return the canonical ASCII host from a domain or URL.

    The returned value never includes credentials, a port, path, query, root
    dot, or leading wildcard.
    """
    if not isinstance(value, str) or not value:
        raise ValueError("host must be a non-empty string")
    if "\\" in value:
        raise ValueError("host cannot contain backslashes")
    if any(character.isspace() for character in value) or any(
        unicodedata.category(character).startswith("C") for character in value
    ):
        raise ValueError("host cannot contain whitespace or control characters")

    parsed = urlsplit(value if "://" in value else f"//{value}")
    host = parsed.hostname
    if host is None:
        raise ValueError("value does not contain a host")
    try:
        parsed.port
    except ValueError as error:
        raise ValueError("invalid port") from error

    host = host.lower()
    if host.startswith("*."):
        host = host[2:]
    if host.endswith("."):
        host = host[:-1]
    if not host:
        raise ValueError("host is empty")

    try:
        ascii_host = idna.encode(
            host, uts46=True, std3_rules=True
        ).decode("ascii").lower()
    except idna.IDNAError as error:
        raise ValueError("host is not valid IDNA") from error

    if len(ascii_host) > 253:
        raise ValueError("host is too long")
    labels = ascii_host.split(".")
    if len(labels) < 2 or any(
        _ASCII_LABEL.fullmatch(label) is None for label in labels
    ):
        raise ValueError("host contains an invalid label")
    try:
        ipaddress.ip_address(ascii_host)
    except ValueError:
        try:
            socket.inet_aton(ascii_host)
        except OSError:
            pass
        else:
            raise ValueError("IP addresses are not host rules")
    else:
        raise ValueError("IP addresses are not host rules")
    return ascii_host


def expand_host_rule(host: str, include_subdomains: bool) -> Tuple[str, ...]:
    """Return immutable exact and optional wildcard rules for a host."""
    normalized = normalize_host(host)
    if include_subdomains:
        return normalized, f"*.{normalized}"
    return (normalized,)


def parse_hosts(output: str) -> Tuple[str, ...]:
    """Parse, canonicalize, deduplicate, and sort hosts from CLI output."""
    hosts = set()
    for token in output.split():
        wildcard = token.startswith("*.")
        try:
            host = normalize_host(token)
        except ValueError:
            continue
        hosts.add(f"*.{host}" if wildcard else host)
    return tuple(sorted(hosts))
