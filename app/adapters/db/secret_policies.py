"""Read secret policies (ADR 0001) from ``secrets_metadata``."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.db.models import SecretMetadata
from app.domain.secret_policy import SecretPolicy


def load_policies(session: Session, names: Iterable[str]) -> dict[str, SecretPolicy]:
    """The policy of each named secret that has one. A secret without a row has no policy,
    which refuses every use."""
    wanted = sorted(set(names))
    if not wanted:
        return {}
    rows = session.execute(select(SecretMetadata).where(SecretMetadata.name.in_(wanted))).scalars()
    return {
        row.name: SecretPolicy(
            name=row.name,
            allowed_hosts=tuple(row.allowed_hosts or ()),
            environments=tuple(row.environments or ()),
        )
        for row in rows
    }
