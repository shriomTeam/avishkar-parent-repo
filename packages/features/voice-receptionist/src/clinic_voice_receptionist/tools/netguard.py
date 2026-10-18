"""Decides which addresses a custom tool may call. Tools run on our servers, so a typed-in URL must never
reach internal services, a private network, or the cloud metadata server (which hands out credentials)."""

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

ALLOWED_PORTS = {443}
BLOCKED_NAME_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".corp")


class BlockedTarget(ValueError):
    """The URL is not allowed. The message is safe to show to staff."""


@dataclass(frozen=True)
class Target:
    scheme: str
    host: str
    port: int
    path_and_query: str


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def parse_url(url: str, *, allow_private: bool = False) -> Target:
    """Check the URL's shape. Does not touch the network."""
    parts = urlsplit(url.strip())
    schemes = ("https", "http") if allow_private else ("https",)
    if parts.scheme not in schemes:
        raise BlockedTarget("Use an HTTPS URL." if not allow_private else "Use an http or https URL.")
    if parts.username or parts.password:
        raise BlockedTarget("Put credentials in the auth header, not in the URL.")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise BlockedTarget("The URL has no host name.")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        raise BlockedTarget("The URL has an invalid port.") from None
    if not allow_private:
        if port not in ALLOWED_PORTS:
            raise BlockedTarget("Only port 443 is allowed.")
        if host == "localhost" or host.endswith(BLOCKED_NAME_SUFFIXES) or "." not in host and ":" not in host:
            raise BlockedTarget("That host name is not a public address.")
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not _is_public(ip):
                raise BlockedTarget("That address is not public.")
    path = parts.path or "/"
    return Target(parts.scheme, host, port, path + (f"?{parts.query}" if parts.query else ""))


async def resolve(target: Target, *, allow_private: bool = False) -> str:
    """Look the host up and return one IP to connect to. Every answer must be public, so a name that also
    points inside our network is refused. Connecting to this IP (not the name) defeats DNS rebinding."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            target.host, target.port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )
    except socket.gaierror:
        raise BlockedTarget("That host name could not be found.") from None
    addresses = [ipaddress.ip_address(info[4][0]) for info in infos]
    if not addresses:
        raise BlockedTarget("That host name could not be found.")
    if not allow_private and not all(_is_public(a) for a in addresses):
        raise BlockedTarget("That host name points to a non-public address.")
    return str(addresses[0])
