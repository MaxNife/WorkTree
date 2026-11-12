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
from app.adapters.db.secret_policies import load_policies
from app.adapters.secrets.base import is_internal_secret
from app.audit.writer import AuditWriter
from app.domain.activity_registry import ActivityRegistry
from app.domain.clock import Clock
from app.domain.enums import Environment, PromotionStatus, Role
from app.domain.secret_policy import check_use, placement_violations
from app.domain.workflow import (
    WorkflowDefinition,
    assert_valid,
    dump_workflow_yaml,
    secret_only_violations,
    secret_refs,
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
    def __init__(
        self,
        clock: Clock,
        audit: AuditWriter,
        registry: ActivityRegistry,
        *,
        enforce_secret_policy: bool = True,
    ) -> None:
        self.clock = clock
        self.audit = audit
        self.registry = registry
        self.enforce_secret_policy = enforce_secret_policy

    def _require_secret_only_inputs(self, definition: WorkflowDefinition) -> None:
        """Outside an Admin's hands, connection inputs must be a secret reference (SEC-1)."""
        problems: list[str] = []
        for step in definition.steps:
            activity = self.registry.get(step.activity) if step.activity else None
            if activity is None:
                continue
            problems.extend(
                f"step {step.id!r} input {field!r}"
                for field in secret_only_violations(step.inputs, activity.secret_only_inputs)
            )
        if problems:
            raise ValidationFailed(
                "only an Admin can type a value for "
                + ", ".join(problems)
                + "; use a single {{ secret:name }} reference (an Admin creates the secret)"
            )

    def _require_secret_placement(self, definition: WorkflowDefinition) -> None:
        """Outside an Admin's hands, a secret goes only into a credential input (ADR 0001 rule 1).

        Any other place (a body, a message, a file, a sub-workflow's inputs, a person's task) could
        carry the value somewhere it does not belong, so it is refused.
        """
        problems: list[str] = []
        for step in definition.steps:
            activity = self.registry.get(step.activity) if step.activity else None
            credentials = activity.credential_fields() if activity is not None else ()
            problems.extend(
                f"step {step.id!r} {where}"
                for where in placement_violations(step.inputs, step.foreach, credentials)
            )
        if problems:
            raise ValidationFailed(
                "a secret may only be used in a credential input; move or remove the secret "
                "reference in " + ", ".join(problems)
            )

    def _require_allowed_destinations(
        self, session: Session, definition: WorkflowDefinition
    ) -> None:
        """ADR 0001 rule 2 at save, for destinations typed into the step. Destinations that
        come from references are checked at dispatch once resolved; environments too."""
        problems: list[str] = []
        for step in definition.steps:
            activity = self.registry.get(step.activity) if step.activity else None
            names = secret_refs(step.inputs)
            if activity is None or not names:
                continue
            hosts = activity.destination_hosts(step.inputs, literal_only=True)
            if not hosts:
                continue
            check = check_use(
                names, load_policies(session, names), environment=None, destinations=hosts
            )
            problems.extend(f"step {step.id!r}: {refusal}" for refusal in check.refusals)
        if problems:
            raise ValidationFailed("refused by the secret policy: " + "; ".join(problems))

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
        reserved = sorted(
            name
            for step in definition.steps
            for name in secret_refs([step.inputs, step.foreach or ""])
            if is_internal_secret(name)
        )
        if reserved:
            raise ValidationFailed(
                f"secret(s) {', '.join(reserved)} are reserved for the platform and cannot be "
                "used in a workflow"
            )
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
            self._require_secret_only_inputs(definition)
            self._require_secret_placement(definition)
        if self.enforce_secret_policy:
            self._require_allowed_destinations(session, definition)

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
            # Page properties (description, owner, tags) can also be edited on the workflow
            # page without a new version. A version save only overwrites them when the
            # definition changed that field since the previous version: last edit wins.
            previous = self._previous_definition(session, workflow)
            workflow.name = definition.name
            if previous is None or definition.description != previous.get("description", ""):
                workflow.description = definition.description
            if definition.owner and (previous is None or definition.owner != previous.get("owner")):
                workflow.owner = definition.owner
            if previous is None or definition.tags != previous.get("tags", []):
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

    def _previous_definition(self, session: Session, workflow: Workflow) -> dict[str, Any] | None:
        if not workflow.latest_version:
            return None
        row = session.execute(
            select(WorkflowVersion).where(
                WorkflowVersion.workflow_id == workflow.id,
                WorkflowVersion.version == workflow.latest_version,
            )
        ).scalar_one_or_none()
        return row.definition if row is not None else None

    def update_metadata(
        self,
        session: Session,
        workflow_id: str,
        changes: dict[str, Any],
        *,
        actor: str,
        correlation_id: str = "",
        source_ip: str = "",
    ) -> Workflow:
        """Edit page properties (description, owner, folder, tags, notes) without a version.

        The name is not editable here: sub-workflow steps and runs refer to it, so a rename
        goes through a new version.
        """
        workflow = self.get(session, workflow_id)
        allowed = ("description", "owner", "folder", "tags", "notes")
        before: dict[str, Any] = {}
        after: dict[str, Any] = {}
        for field in allowed:
            if field in changes and changes[field] != getattr(workflow, field):
                before[field] = getattr(workflow, field)
                after[field] = changes[field]
                setattr(workflow, field, changes[field])
        if not after:
            return workflow
        workflow.updated_at = self.clock.now()
        self.audit.write(
            session,
            actor=actor,
            action="workflow.update",
            resource_type="workflow",
            resource_id=workflow.id,
            source_ip=source_ip,
            before=before,
            after=after,
            correlation_id=correlation_id,
        )
        return workflow

    def subworkflow_status(
        self, session: Session, definition: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Each sub-workflow step with its pinned and latest version, for the Studio's
        "newer version available" flag."""
        result: list[dict[str, Any]] = []
        for step in definition.get("steps", []):
            ref = step.get("workflow") if isinstance(step, dict) else None
            if not isinstance(ref, dict) or not ref.get("name"):
                continue
            target = session.execute(
                select(Workflow).where(Workflow.name == ref["name"])
            ).scalar_one_or_none()
            pinned = int(ref.get("version") or 0)
            latest = target.latest_version if target is not None else None
            result.append(
                {
                    "step_id": step.get("id"),
                    "workflow_name": ref["name"],
                    "workflow_id": target.id if target is not None else None,
                    "pinned_version": pinned,
                    "latest_version": latest,
                    "newer_version_available": latest is not None and latest > pinned,
                }
            )
        return result

    def promoted_versions(self, session: Session, workflow: Workflow) -> dict[str, int | None]:
        """Latest version for dev, and the most recently approved promotion for test and prod
        (None when nothing was promoted there). Prod runs only the promoted version."""
        result: dict[str, int | None] = {Environment.DEV.value: workflow.latest_version or None}
        for environment in (Environment.TEST, Environment.PROD):
            promotion = self.approved_in(session, workflow.id, environment)
            result[environment.value] = promotion.version if promotion else None
        return result

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
