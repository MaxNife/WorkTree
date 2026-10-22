"""Workflow registry: immutable versions, environments, promotion and segregation of duties."""

from __future__ import annotations

import difflib
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.db.models import Promotion, Workflow, WorkflowVersion
from app.audit.writer import AuditWriter
from app.domain.activity_registry import ActivityRegistry
from app.domain.clock import Clock
from app.domain.enums import Environment, PromotionStatus, Role
from app.domain.workflow import (
    WorkflowDefinition,
    assert_valid,
    dump_workflow_yaml,
)
from app.errors import Conflict, Forbidden, NotFound, ValidationFailed

PROMOTION_CHAIN: dict[Environment, Environment | None] = {
    Environment.DEV: None,
    Environment.TEST: Environment.DEV,
    Environment.PROD: Environment.TEST,
}


def checksum(definition: WorkflowDefinition) -> str:
    payload = json.dumps(definition.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class VersionSummary:
    id: str
    version: int
    checksum: str
    created_by: str
    created_at: Any


class WorkflowService:
    def __init__(self, clock: Clock, audit: AuditWriter, registry: ActivityRegistry) -> None:
        self.clock = clock
        self.audit = audit
        self.registry = registry

    def save(
        self,
        session: Session,
        definition: WorkflowDefinition,
        *,
        actor: str,
        actor_roles: list[Role],
        workflow_id: str | None = None,
        correlation_id: str = "",
        source_ip: str = "",
    ) -> tuple[Workflow, WorkflowVersion]:
        if Role.ADMIN not in actor_roles and Role.AUTHOR not in actor_roles:
            raise Forbidden("only an Author or Admin can save a workflow")
        assert_valid(definition, self.registry.names())
        if Role.ADMIN not in actor_roles:
            restricted = sorted(
                {
                    step.activity
                    for step in definition.steps
                    if step.activity
                    and (activity := self.registry.get(step.activity)) is not None
                    and activity.requires_admin_author
                }
            )
            if restricted:
                raise Forbidden(
                    "only an Admin can save a workflow that uses "
                    + ", ".join(restricted)
                    + " (these activities run code on the server)"
                )

        if workflow_id is None:
            workflow = session.execute(
                select(Workflow).where(Workflow.name == definition.name)
            ).scalar_one_or_none()
        else:
            workflow = session.get(Workflow, workflow_id)
            if workflow is None:
                raise NotFound(f"workflow {workflow_id} not found")
            existing_name = session.execute(
                select(Workflow).where(Workflow.name == definition.name, Workflow.id != workflow.id)
            ).scalar_one_or_none()
            if existing_name is not None:
                raise Conflict(f"another workflow is already named {definition.name!r}")

        before = None
        if workflow is None:
            workflow = Workflow(
                name=definition.name,
                description=definition.description,
                owner=definition.owner or actor,
                tags=definition.tags,
                created_by=actor,
                created_at=self.clock.now(),
                updated_at=self.clock.now(),
            )
            session.add(workflow)
            session.flush()
        else:
            before = {
                "name": workflow.name,
                "description": workflow.description,
                "owner": workflow.owner,
                "tags": workflow.tags,
            }
            workflow.name = definition.name
            workflow.description = definition.description
            workflow.owner = definition.owner or workflow.owner
            workflow.tags = definition.tags
            workflow.updated_at = self.clock.now()

        workflow.latest_version = (workflow.latest_version or 0) + 1
        activity_versions = {
            step.activity: self.registry.get(step.activity).version  # type: ignore[union-attr]
            for step in definition.steps
            if step.activity and self.registry.get(step.activity) is not None
        }
        version = WorkflowVersion(
            workflow_id=workflow.id,
            version=workflow.latest_version,
            definition=definition.model_dump(mode="json"),
            checksum=checksum(definition),
            created_by=actor,
            created_at=self.clock.now(),
            activity_versions=activity_versions,
        )
        session.add(version)
        session.flush()
        self.audit.write(
            session,
            actor=actor,
            action="workflow.version.create",
            resource_type="workflow",
            resource_id=workflow.id,
            source_ip=source_ip,
            before=before,
            after={
                "name": definition.name,
                "version": version.version,
                "checksum": version.checksum,
            },
            correlation_id=correlation_id,
        )
        return workflow, version

    def get(self, session: Session, workflow_id: str) -> Workflow:
        workflow = session.get(Workflow, workflow_id)
        if workflow is None:
            raise NotFound(f"workflow {workflow_id} not found")
        return workflow

    def by_name(self, session: Session, name: str) -> Workflow:
        workflow = session.execute(
            select(Workflow).where(Workflow.name == name)
        ).scalar_one_or_none()
        if workflow is None:
            raise NotFound(f"workflow {name!r} not found")
        return workflow

    def list_workflows(self, session: Session, *, include_archived: bool = False) -> list[Workflow]:
        query = select(Workflow).order_by(Workflow.name)
        if not include_archived:
            query = query.where(Workflow.archived.is_(False))
        return list(session.execute(query).scalars())

    def versions(self, session: Session, workflow_id: str) -> list[WorkflowVersion]:
        return list(
            session.execute(
                select(WorkflowVersion)
                .where(WorkflowVersion.workflow_id == workflow_id)
                .order_by(WorkflowVersion.version.desc())
            ).scalars()
        )

    def version(self, session: Session, workflow_id: str, version: int) -> WorkflowVersion:
        row = session.execute(
            select(WorkflowVersion).where(
                WorkflowVersion.workflow_id == workflow_id,
                WorkflowVersion.version == version,
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFound(f"workflow version {workflow_id}@{version} not found")
        return row

    def latest_version(self, session: Session, workflow_id: str) -> WorkflowVersion:
        row = session.execute(
            select(WorkflowVersion)
            .where(WorkflowVersion.workflow_id == workflow_id)
            .order_by(WorkflowVersion.version.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            raise NotFound(f"workflow {workflow_id} has no versions")
        return row

    def definition(self, version: WorkflowVersion) -> WorkflowDefinition:
        return WorkflowDefinition.model_validate(version.definition)

    # ---- promotion -------------------------------------------------------------
    def request_promotion(
        self,
        session: Session,
        *,
        workflow_id: str,
        version_number: int,
        to_environment: Environment,
        actor: str,
        actor_roles: list[Role],
        reason: str = "",
        correlation_id: str = "",
        source_ip: str = "",
    ) -> Promotion:
        if to_environment is Environment.DEV:
            raise ValidationFailed(
                "dev is the starting environment and cannot be a promotion target"
            )
        if (
            Role.ADMIN not in actor_roles
            and Role.AUTHOR not in actor_roles
            and Role.APPROVER not in actor_roles
        ):
            raise Forbidden("only an Author, Approver or Admin can request a promotion")
        workflow = self.get(session, workflow_id)
        version = self.version(session, workflow_id, version_number)
        from_environment = PROMOTION_CHAIN[to_environment]
        assert from_environment is not None
        if to_environment is Environment.PROD:
            approved_in_test = session.execute(
                select(Promotion.id).where(
                    Promotion.workflow_id == workflow_id,
                    Promotion.version_id == version.id,
                    Promotion.to_environment == Environment.TEST.value,
                    Promotion.status == PromotionStatus.APPROVED.value,
                )
            ).first()
            if approved_in_test is None:
                raise ValidationFailed(
                    f"version {version_number} must be approved in test before it can be "
                    "promoted to prod"
                )
        duplicate = session.execute(
            select(Promotion).where(
                Promotion.workflow_id == workflow_id,
                Promotion.version_id == version.id,
                Promotion.to_environment == to_environment.value,
                Promotion.status == PromotionStatus.PENDING.value,
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            raise Conflict("a promotion request for this version and environment already exists")
        promotion = Promotion(
            workflow_id=workflow.id,
            version_id=version.id,
            version=version.version,
            from_environment=from_environment.value,
            to_environment=to_environment.value,
            status=PromotionStatus.PENDING.value,
            requested_by=actor,
            reason=reason,
            requested_at=self.clock.now(),
        )
        session.add(promotion)
        session.flush()
        self.audit.write(
            session,
            actor=actor,
            action="promotion.request",
            resource_type="promotion",
            resource_id=promotion.id,
            source_ip=source_ip,
            after={
                "workflow": workflow.name,
                "version": version.version,
                "to": to_environment.value,
            },
            correlation_id=correlation_id,
        )
        return promotion

    def decide_promotion(
        self,
        session: Session,
        *,
        promotion_id: str,
        approve: bool,
        actor: str,
        actor_roles: list[Role],
        reason: str = "",
        correlation_id: str = "",
        source_ip: str = "",
    ) -> Promotion:
        if Role.ADMIN not in actor_roles and Role.APPROVER not in actor_roles:
            raise Forbidden("only an Approver or Admin can decide a promotion")
        promotion = session.get(Promotion, promotion_id)
        if promotion is None:
            raise NotFound("promotion not found")
        if promotion.status != PromotionStatus.PENDING.value:
            raise Conflict(f"promotion is already {promotion.status}")
        if promotion.requested_by == actor:
            raise Forbidden("segregation of duties: you cannot decide your own promotion request")
        workflow = self.get(session, promotion.workflow_id)
        version = session.get(WorkflowVersion, promotion.version_id)
        if version is None:
            raise NotFound("promoted version not found")
        if version.created_by == actor:
            raise Forbidden(
                "segregation of duties: an author cannot approve promotion of their own workflow"
            )
        promotion.status = (
            PromotionStatus.APPROVED.value if approve else PromotionStatus.REJECTED.value
        )
        promotion.decided_by = actor
        promotion.decided_at = self.clock.now()
        promotion.reason = reason
        self.audit.write(
            session,
            actor=actor,
            action="promotion.approve" if approve else "promotion.reject",
            resource_type="promotion",
            resource_id=promotion.id,
            source_ip=source_ip,
            before={"status": PromotionStatus.PENDING.value},
            after={
                "status": promotion.status,
                "workflow": workflow.name,
                "version": version.version,
                "to": promotion.to_environment,
                "reason": reason,
            },
            correlation_id=correlation_id,
        )
        return promotion

    def approved_in(
        self, session: Session, workflow_id: str, environment: Environment
    ) -> Promotion | None:
        return session.execute(
            select(Promotion)
            .where(
                Promotion.workflow_id == workflow_id,
                Promotion.to_environment == environment.value,
                Promotion.status == PromotionStatus.APPROVED.value,
            )
            .order_by(Promotion.decided_at.desc(), Promotion.version.desc())
            .limit(1)
        ).scalar_one_or_none()

    def runnable_version(
        self, session: Session, workflow: Workflow, environment: Environment
    ) -> WorkflowVersion:
        if environment is Environment.PROD:
            promotion = self.approved_in(session, workflow.id, Environment.PROD)
            if promotion is None:
                raise Forbidden(f"workflow {workflow.name!r} has no promoted version for prod")
            return self.version(session, workflow.id, promotion.version)
        return self.latest_version(session, workflow.id)

    def promotion_list(
        self, session: Session, *, workflow_id: str | None = None, status: str | None = None
    ) -> list[Promotion]:
        query = select(Promotion).order_by(Promotion.requested_at.desc())
        if workflow_id:
            query = query.where(Promotion.workflow_id == workflow_id)
        if status:
            query = query.where(Promotion.status == status)
        return list(session.execute(query).scalars())

    def diff(
        self, session: Session, workflow_id: str, from_version: int, to_version: int
    ) -> dict[str, Any]:
        left = self.version(session, workflow_id, from_version)
        right = self.version(session, workflow_id, to_version)
        left_yaml = dump_workflow_yaml(WorkflowDefinition.model_validate(left.definition))
        right_yaml = dump_workflow_yaml(WorkflowDefinition.model_validate(right.definition))
        lines = list(
            difflib.unified_diff(
                left_yaml.splitlines(),
                right_yaml.splitlines(),
                fromfile=f"v{from_version}",
                tofile=f"v{to_version}",
                lineterm="",
            )
        )
        left_steps = {s["id"]: s for s in left.definition.get("steps", [])}
        right_steps = {s["id"]: s for s in right.definition.get("steps", [])}
        changes = {
            "added": sorted(set(right_steps) - set(left_steps)),
            "removed": sorted(set(left_steps) - set(right_steps)),
            "changed": sorted(
                step_id
                for step_id in set(left_steps) & set(right_steps)
                if left_steps[step_id] != right_steps[step_id]
            ),
        }
        return {
            "from_version": from_version,
            "to_version": to_version,
            "diff": "\n".join(lines),
            "steps": changes,
        }

    def newer_version_available(
        self, session: Session, workflow_name: str, pinned_version: int
    ) -> bool:
        workflow = session.execute(
            select(Workflow).where(Workflow.name == workflow_name)
        ).scalar_one_or_none()
        return workflow is not None and workflow.latest_version > pinned_version

    def count(self, session: Session) -> int:
        return int(session.execute(select(func.count(Workflow.id))).scalar_one())
