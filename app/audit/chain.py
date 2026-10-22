"""Hash-chain computation and verification for the audit log."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

GENESIS_HASH = ""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def compute_hash(
    *,
    ts: datetime,
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str,
    source_ip: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    correlation_id: str,
    prev_hash: str,
) -> str:
    iso = ts.astimezone(UTC).isoformat()
    payload = canonical(
        {
            "ts": iso,
            "actor": actor,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "source_ip": source_ip,
            "before": before,
            "after": after,
            "correlation_id": correlation_id,
            "prev_hash": prev_hash,
        }
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuditCheck:
    ok: bool
    rows: int
    first_bad_id: int | None = None
    message: str = ""


def verify_rows(rows: list[Any]) -> AuditCheck:
    """Verify an ordered list of AuditLog rows (or row-like objects)."""
    previous = GENESIS_HASH
    for expected_index, row in enumerate(rows, start=1):
        if row.id != expected_index:
            return AuditCheck(
                ok=False,
                rows=len(rows),
                first_bad_id=row.id,
                message=f"audit row id gap: expected {expected_index}, found {row.id}",
            )
        if row.prev_hash != previous:
            return AuditCheck(
                ok=False,
                rows=len(rows),
                first_bad_id=row.id,
                message=f"broken chain at audit row {row.id}",
            )
        expected = compute_hash(
            ts=row.ts,
            actor=row.actor,
            action=row.action,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            source_ip=row.source_ip,
            before=row.before,
            after=row.after,
            correlation_id=row.correlation_id,
            prev_hash=row.prev_hash,
        )
        if expected != row.hash:
            return AuditCheck(
                ok=False,
                rows=len(rows),
                first_bad_id=row.id,
                message=f"tampered audit row {row.id}",
            )
        previous = row.hash
    return AuditCheck(ok=True, rows=len(rows), message="audit chain verified")
