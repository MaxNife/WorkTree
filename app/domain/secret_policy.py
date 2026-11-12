"""Where secrets may be used (ADR 0001). Pure rules: no database, no network.

Rule 1, placement: outside an Admin's hands, a ``{{ secret:name }}`` reference may appear only in
an activity's credential inputs. Rule 2, destination: a step that uses a secret connects only to
hosts on that secret's ``allowed_hosts``. Rule 3, environment: a step uses a secret only in an
environment on its ``environments`` list. Rule 4 (egress) lives in ``app.adapters.net``.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from app.domain.enums import Environment
from app.domain.workflow import JsonValue, secret_refs

# A host pattern: an exact name, or ``*.`` followed by a domain for its subdomains only.
_LABEL = r"(?!-)[a-z0-9-]{1,63}(?<!-)"


def placement_violations(
    inputs: Mapping[str, JsonValue], foreach: str | None, credential_fields: Iterable[str]
) -> list[str]:
    """Where a step puts a secret reference outside its credential inputs (rule 1).

    Scans exactly what can hold a reference the engine resolves: every input, and ``foreach``.
    A credential input may hold a reference anywhere inside it (a header value, for example).
    """
    allowed = set(credential_fields)
    found = [
        f"input {name!r}"
        for name, value in inputs.items()
        if name not in allowed and secret_refs(value)
    ]
    if foreach and secret_refs(foreach):
        found.append("foreach")
    return found


def normalise_host(host: str) -> str:
    """Lowercase, without a trailing dot or the brackets around an IPv6 literal."""
    host = host.strip().lower().rstrip(".")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host


def host_matches(host: str, pattern: str) -> bool:
    """True when ``host`` is ``pattern``, or a subdomain of ``d`` for a ``*.d`` pattern.

    ``*.example.com`` matches ``a.example.com`` and ``a.b.example.com``, never ``example.com``
    itself and never ``badexample.com``. Ports are not part of either side.
    """
    host = normalise_host(host)
    pattern = normalise_host(pattern)
    if not host or not pattern:
        return False
    if pattern.startswith("*."):
        domain = pattern[2:]
        return bool(domain) and host.endswith("." + domain)
    return host == pattern


def valid_host_pattern(pattern: str) -> bool:
    """An exact host, an IP literal, or ``*.`` followed by a domain of at least two labels."""
    value = normalise_host(pattern)
    if not value or len(value) > 253:
        return False
    try:
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        return True
    wildcard = value.startswith("*.")
    labels = (value[2:] if wildcard else value).split(".")
    if wildcard and len(labels) < 2:
        return False
    return all(re.fullmatch(_LABEL, label) for label in labels)


def clean_hosts(hosts: Iterable[str]) -> list[str]:
    """Normalised, de-duplicated host patterns. ValueError names any that is not valid."""
    values = list(hosts)
    bad = [host for host in values if not valid_host_pattern(host)]
    if bad:
        raise ValueError(
            "allowed hosts are exact host names, IP addresses or '*.' and a domain "
            "(subdomains only); not valid: " + ", ".join(bad[:10])
        )
    return list(dict.fromkeys(normalise_host(host) for host in values))


def clean_environments(environments: Iterable[object]) -> list[str]:
    """Environment names in their fixed order (dev, test, prod). ValueError for any other."""
    wanted = {str(getattr(env, "value", env)).strip().lower() for env in environments}
    known = [env.value for env in Environment]
    unknown = sorted(wanted - set(known))
    if unknown:
        raise ValueError("unknown environment(s): " + ", ".join(unknown))
    return [name for name in known if name in wanted]


@dataclass(frozen=True)
class SecretPolicy:
    """The Admin-managed policy of one secret. Empty lists refuse (ADR 0001)."""

    name: str
    allowed_hosts: tuple[str, ...] = ()
    environments: tuple[str, ...] = ()


@dataclass
class PolicyCheck:
    """Rules 2 and 3 for one step: refusals, each naming the secret and the setting to change."""

    refusals: list[str] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return not self.refusals


def check_use(
    secrets: Iterable[str],
    policies: Mapping[str, SecretPolicy],
    *,
    environment: str | None,
    destinations: Iterable[str] | None,
) -> PolicyCheck:
    """Check rules 2 and 3 for a step that uses ``secrets``.

    ``destinations`` is the list of hosts the step connects to, or None when the activity has
    no network destination (a local file, or a database whose address is inside the secret);
    then only rule 3 applies. An empty string in ``destinations`` is a destination that could
    not be parsed, and refuses. ``environment`` None skips rule 3 (a save, before any run).
    """
    result = PolicyCheck()
    hosts = None if destinations is None else list(destinations)
    for name in secrets:
        policy = policies.get(name)
        if policy is None:
            result.refusals.append(
                f"secret {name!r} has no policy; an Admin sets its environments and allowed hosts"
            )
            continue
        if environment is not None and environment not in policy.environments:
            listed = ", ".join(policy.environments) or "none"
            result.refusals.append(
                f"secret {name!r} may not be used in {environment} (its environments: {listed}); "
                "an Admin can add it to the secret's environments"
            )
        if hosts is None:
            continue
        for host in hosts:
            if not host:
                result.refusals.append(
                    f"secret {name!r} is used by a step whose destination could not be read"
                )
            elif not any(host_matches(host, pattern) for pattern in policy.allowed_hosts):
                result.refusals.append(
                    f"secret {name!r} may not be sent to {host} (not in its allowed hosts); "
                    "an Admin can add the host to the secret's allowed hosts"
                )
    return result
