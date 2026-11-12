"""Read the host a destination input names (ADR 0001 rule 2).

URLs are parsed with ``httpx.URL``, the parser the HTTP activities connect with, so the host a
policy is checked against is the host the request goes to (``urlparse`` disagrees with it on
backslashes, ``@`` and Unicode). Hosts come back IDNA-encoded and lowercase.
"""

from __future__ import annotations

import ipaddress
import re

import httpx

from app.domain.secret_policy import normalise_host

_PLAIN_HOST = re.compile(r"[a-z0-9.\-]+")


def destination_host(value: object) -> str | None:
    """The host ``value`` names.

    None means the field is not in use: empty, or a path relative to another destination field
    (``/portal/login`` next to a ``base_url``). An empty string means the value names a
    destination that cannot be read, or still holds a ``{{ }}`` reference; a policy refuses it.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return None
    if "{{" in text:
        return ""
    if text.startswith("/") and not text.startswith("//"):
        return None
    if "://" in text or text.startswith("//"):
        return _url_host(text)
    return _plain_host(text)


def _url_host(text: str) -> str:
    try:
        url = httpx.URL(text)
    except Exception:
        return ""
    try:
        host = url.raw_host.decode("ascii")
    except UnicodeDecodeError:
        return ""
    return normalise_host(host)


def _plain_host(text: str) -> str:
    """A host field such as ``smtp_host``: a name or an IP literal, with no port."""
    candidate = normalise_host(text)
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        pass
    try:
        encoded = candidate.encode("idna").decode("ascii")
    except UnicodeError:
        return ""
    return encoded if _PLAIN_HOST.fullmatch(encoded) else ""
