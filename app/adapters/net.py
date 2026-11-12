"""Egress control for activities (ADR 0001 rule 4, docs/02 section 9.4).

``check_destination`` resolves a host, checks every address it resolves to against the denied
networks (loopback, link-local and the cloud metadata addresses by default) and, when set, the
allowed networks, and returns the addresses that passed. The clients below then connect to an
address that was checked, never resolving the name a second time, so a name that changes between
the check and the connection cannot reach a denied address.

The policy reaches an activity child through ``UAF_CHILD_EGRESS`` (the child does not load
config.yaml); without it the defaults apply.

Not covered, and documented as remaining risk: database drivers (their address is inside a
secret an Admin set), a Playwright browser, which resolves names itself, and ``run_python`` and
``legacy_robot_wrapper``, which run code with ordinary sockets. All three of the last are
Admin-only activities.
"""

from __future__ import annotations

import ipaddress
import json
import os
import smtplib
import socket
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import httpcore
import httpx

EGRESS_ENV = "UAF_CHILD_EGRESS"

# Loopback, "this network", link-local (the cloud metadata address 169.254.169.254 among them)
# and AWS's IPv6 metadata address. Private ranges stay open: internal systems are the normal case.
DEFAULT_DENIED_NETWORKS: tuple[str, ...] = (
    "0.0.0.0/8",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "::/128",
    "::1/128",
    "fe80::/10",
    "fd00:ec2::254/128",
)

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class EgressDenied(ConnectionError):
    """A connection the egress policy does not allow."""


@dataclass(frozen=True)
class EgressPolicy:
    denied: tuple[IPNetwork, ...]
    # Empty: every address that is not denied is allowed.
    allowed: tuple[IPNetwork, ...] = ()

    @classmethod
    def build(cls, denied: Iterable[str], allowed: Iterable[str] = ()) -> EgressPolicy:
        return cls(
            denied=tuple(ipaddress.ip_network(net, strict=False) for net in denied),
            allowed=tuple(ipaddress.ip_network(net, strict=False) for net in allowed),
        )

    @classmethod
    def current(cls) -> EgressPolicy:
        """The policy the worker passed to this process, or the defaults."""
        raw = os.environ.get(EGRESS_ENV)
        if not raw:
            return cls.build(DEFAULT_DENIED_NETWORKS)
        try:
            data = json.loads(raw)
            return cls.build(data.get("denied", DEFAULT_DENIED_NETWORKS), data.get("allowed", ()))
        except (ValueError, TypeError, AttributeError):
            # A malformed policy must not open the network: fall back to the defaults.
            return cls.build(DEFAULT_DENIED_NETWORKS)

    def refusal(self, address: IPAddress) -> str | None:
        """Why ``address`` may not be reached, or None when it may."""
        candidates: list[IPAddress] = [address]
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            candidates.append(address.ipv4_mapped)
        for candidate in candidates:
            for network in self.denied:
                if candidate.version == network.version and candidate in network:
                    return f"{address} is in the denied network {network}"
        if self.allowed and not any(
            candidate.version == network.version and candidate in network
            for candidate in candidates
            for network in self.allowed
        ):
            return f"{address} is outside the allowed networks"
        return None


def env_value(denied: Iterable[str], allowed: Iterable[str] = ()) -> str:
    """The ``UAF_CHILD_EGRESS`` value for these settings."""
    return json.dumps({"denied": list(denied), "allowed": list(allowed)})


def _resolve(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def check_destination(
    host: str, port: int, purpose: str = "", *, policy: EgressPolicy | None = None
) -> list[str]:
    """Resolve ``host`` and return its addresses when every one of them is allowed.

    Refuses when any address is denied (a name that resolves to both a public and a loopback
    address is refused), and when the name does not resolve.
    """
    rules = policy or EgressPolicy.current()
    label = f" for {purpose}" if purpose else ""
    try:
        addresses = _resolve(host, port)
    except OSError as exc:
        raise EgressDenied(f"cannot resolve {host}{label}: {exc}") from exc
    if not addresses:
        raise EgressDenied(f"{host} does not resolve to any address{label}")
    for text in addresses:
        try:
            address = ipaddress.ip_address(text.split("%", 1)[0])
        except ValueError as exc:
            raise EgressDenied(f"{host} resolved to an unreadable address{label}") from exc
        reason = rules.refusal(address)
        if reason is not None:
            raise EgressDenied(f"connection to {host}{label} refused: {reason}")
    return addresses


def checked_socket(host: str, port: int, timeout: float | None, purpose: str = "") -> socket.socket:
    """A TCP socket connected to a checked address of ``host``, trying each address in turn
    (a dual-stack name falls back to IPv4 when IPv6 has no route)."""
    last: OSError | None = None
    for address in check_destination(host, port, purpose):
        try:
            return socket.create_connection((address, port), timeout)
        except OSError as exc:
            last = exc
    assert last is not None
    raise last


class _CheckedBackend(httpcore.NetworkBackend):
    """httpcore's network backend, connecting only to checked addresses. TLS still verifies the
    certificate against the host name: httpcore passes the origin's name as server_hostname."""

    def __init__(self, inner: httpcore.NetworkBackend) -> None:
        self._inner = inner

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.NetworkStream:
        last: Exception | None = None
        for address in check_destination(host, port, "an HTTP request"):
            try:
                return self._inner.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout, OSError) as exc:
                last = exc
        assert last is not None
        raise last

    def connect_unix_socket(
        self, path: str, timeout: float | None = None, socket_options: Iterable[Any] | None = None
    ) -> httpcore.NetworkStream:
        raise EgressDenied("activities may not connect to a Unix socket")

    def sleep(self, seconds: float) -> None:
        self._inner.sleep(seconds)


class CheckedTransport(httpx.HTTPTransport):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # httpx does not expose the network backend; the test suite fails if this stops working.
        pool: Any = self._pool
        pool._network_backend = _CheckedBackend(pool._network_backend or httpcore.SyncBackend())


def checked_client(**kwargs: Any) -> httpx.Client:
    """An httpx client for activities: every connection goes to a checked address, redirects are
    not followed, and proxy settings from the environment are ignored (a proxy would make the
    check guard the proxy, not the destination)."""
    kwargs.setdefault("follow_redirects", False)
    transport_options = {key: kwargs.pop(key) for key in ("verify", "cert") if key in kwargs}
    return httpx.Client(transport=CheckedTransport(**transport_options), trust_env=False, **kwargs)


class CheckedSMTP(smtplib.SMTP):
    """smtplib.SMTP that connects to a checked address. STARTTLS still checks the certificate
    against the host name, which smtplib keeps in ``_host``."""

    def _get_socket(self, host: str, port: int, timeout: float) -> socket.socket:
        if timeout is not None and not timeout:
            raise ValueError("Non-blocking socket (timeout=0) is not supported")
        return checked_socket(host, port, timeout, "SMTP")
