"""Secret policies (ADR 0001), shared by the Admin API and the ``uaf secrets`` command."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.db.models import SecretMetadata
from app.adapters.secrets.base import SecretStore, is_internal_secret
from app.audit.writer import AuditWriter
from app.domain.clock import Clock
from app.domain.secret_policy import clean_environments, clean_hosts
from app.errors import NotFound, ValidationFailed


@dataclass(frozen=True)
class SecretRow:
    """What may be shown about a secret: never its value."""

    name: str
    source: str
    allowed_hosts: list[str]
    environments: list[str]

    @property
    def refused_everywhere(self) -> bool:
        """No environment listed: every use of the secret is refused."""
        return not self.environments


def policy_of(row: SecretMetadata | None) -> dict[str, list[str]]:
    return {
        "allowed_hosts": list(row.allowed_hosts) if row else [],
        "environments": list(row.environments) if row else [],
    }


def list_secrets(session: Session, store: SecretStore) -> list[SecretRow]:
    """Every secret a workflow could use, with its policy. Platform secrets are left out."""
    rows = {row.name: row for row in session.execute(select(SecretMetadata)).scalars()}
    result: list[SecretRow] = []
    for info in sorted(store.list_metadata(), key=lambda item: item.name):
        if is_internal_secret(info.name):
            continue
        policy = policy_of(rows.get(info.name))
        result.append(SecretRow(info.name, info.source, **policy))
    return result


def set_policy(
    session: Session,
    *,
    store: SecretStore,
    audit: AuditWriter,
    clock: Clock,
    name: str,
    allowed_hosts: Iterable[str],
    environments: Iterable[Any],
    actor: str,
    source_ip: str = "",
    correlation_id: str = "",
) -> dict[str, list[str]]:
    """Replace a secret's policy without changing its value, and audit it as ``secret.policy``.
    Empty lists refuse every use."""
    if is_internal_secret(name):
        raise ValidationFailed(f"{name} is reserved for the platform and has no policy")
    if name not in store.names():
        raise NotFound(f"secret {name} not found")
    try:
        hosts = clean_hosts(allowed_hosts)
        envs = clean_environments(environments)
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc
    row = session.get(SecretMetadata, name)
    before = policy_of(row)
    if row is None:
        row = SecretMetadata(name=name, created_at=clock.now())
        session.add(row)
    row.allowed_hosts = hosts
    row.environments = envs
    after = policy_of(row)
    audit.write(
        session,
        actor=actor,
        action="secret.policy",
        resource_type="secret",
        resource_id=name,
        source_ip=source_ip,
        before=before,
        after=after,
        correlation_id=correlation_id,
    )
    return after
