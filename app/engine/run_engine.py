"""The run engine: dispatch, route, retry, suspend, resume and crash recovery.

One run advances one step at a time. The run row, step row, attempt row and the next bus job
are written in the same transaction, so a crash leaves a resumable state.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.db.database import Database
from app.adapters.db.models import (
    Artifact,
    Incident,
    Promotion,
    ResumeToken,
    Run,
    RunStep,
    StepAttempt,
    Task,
    Workflow,
    WorkflowVersion,
)
from app.audit.writer import AuditWriter
from app.bus.db_bus import DbMessageBus
from app.domain.activity_registry import ActivityRegistry
from app.domain.clock import Clock
from app.domain.enums import (
    TERMINAL_RUN_STATUSES,
    Environment,
    Outcome,
    PromotionStatus,
    RunStatus,
    StepState,
)
from app.domain.envelope import JobEnvelope, ResultEnvelope
from app.domain.workflow import (
    ReferenceError,
    ResolveContext,
    Step,
    WorkflowDefinition,
    resolve_value,
    secret_refs,
)
from app.errors import Conflict, DuplicateRun, Forbidden, NotFound
from app.logging_setup import get_logger
from app.security.masking import get_masker

ACTIVE_RUN_STATUSES = {RunStatus.PENDING.value, RunStatus.RUNNING.value, RunStatus.SUSPENDED.value}
WAITING_STATES = {StepState.WAITING.value}


class RunEngine:
    def __init__(
        self,
        *,
        database: Database,
        clock: Clock,
        audit: AuditWriter,
        bus: DbMessageBus,
        registry: ActivityRegistry,
        workspaces: Path,
        default_timeout_seconds: int = 300,
        max_persisted_output_bytes: int = 64 * 1024,
        event_sink: Any = None,
    ) -> None:
        self.database = database
        self.clock = clock
        self.audit = audit
        self.bus = bus
        self.registry = registry
        self.workspaces = workspaces
        self.default_timeout_seconds = default_timeout_seconds
        self.max_persisted_output_bytes = max_persisted_output_bytes
        self.event_sink = event_sink
        self.log = get_logger(__name__)

    def _emit(self, event: dict[str, Any]) -> None:
        if self.event_sink is None:
            return
        try:
            self.event_sink(event)
        except Exception:  # pragma: no cover - event delivery must not break the engine
            self.log.warning("event_publish_failed")

    # ------------------------------------------------------------------ start
    def start_run(
        self,
        *,
        workflow_id: str,
        environment: str = "dev",
        trigger: str = "manual",
        requested_by: str = "",
        inputs: dict[str, Any] | None = None,
        correlation_id: str = "",
        trigger_detail: dict[str, Any] | None = None,
        parent_run_id: str | None = None,
        version_number: int | None = None,
    ) -> Run:
        with self.database.session() as session:
            workflow = session.get(Workflow, workflow_id)
            if workflow is None:
                raise NotFound(f"workflow {workflow_id} not found")
            version = self._resolve_version(
                session,
                workflow,
                environment,
                version_number,
                require_promoted=parent_run_id is None,
            )
            definition = WorkflowDefinition.model_validate(version.definition)
            run_inputs = inputs or {}
            duplicate_key = self._duplicate_key(definition, run_inputs)
            details = dict(trigger_detail or {})

            if parent_run_id is None and definition.settings.duplicate_guard.value != "allow":
                active = self._active_duplicate(session, workflow.id, duplicate_key)
                if active is not None and definition.settings.duplicate_guard.value == "reject":
                    self.audit.write(
                        session,
                        actor=requested_by or "system",
                        action="run.duplicate_rejected",
                        resource_type="workflow",
                        resource_id=workflow.id,
                        after={"duplicate_of": active.id, "key": duplicate_key},
                        correlation_id=correlation_id,
                    )
                    raise DuplicateRun(
                        f"workflow {workflow.name!r} is already running "
                        f"(run {active.id}, key {duplicate_key!r})",
                        details={"duplicate_of": active.id, "key": duplicate_key},
                    )
                if active is not None:
                    details["queued"] = True
                    details["duplicate_of"] = active.id

            run = Run(
                workflow_id=workflow.id,
                workflow_name=workflow.name,
                version_id=version.id,
                version=version.version,
                environment=environment,
                status=RunStatus.PENDING.value,
                trigger=trigger,
                trigger_detail=details,
                correlation_id=correlation_id or "",
                workspace="",
                current_step=definition.start_step.id,
                inputs=run_inputs,
                requested_by=requested_by,
                duplicate_key=duplicate_key,
                parent_run_id=parent_run_id,
                created_at=self.clock.now(),
                updated_at=self.clock.now(),
            )
            session.add(run)
            session.flush()
            workspace = self.workspaces / run.id
            workspace.mkdir(parents=True, exist_ok=True)
            run.workspace = str(workspace)
            run.status = (
                RunStatus.PENDING.value if details.get("queued") else RunStatus.RUNNING.value
            )
            run.started_at = self.clock.now()
            self.audit.write(
                session,
                actor=requested_by or "system",
                action="run.trigger",
                resource_type="run",
                resource_id=run.id,
                after={
                    "workflow": workflow.name,
                    "version": version.version,
                    "environment": environment,
                    "trigger": trigger,
                    "duplicate_key": duplicate_key,
                },
                correlation_id=run.correlation_id,
            )
            self._advance(session, run, definition)
            session.flush()
            session.expunge(run)
            return run

    def _resolve_version(
        self,
        session: Session,
        workflow: Workflow,
        environment: str,
        version_number: int | None,
        *,
        require_promoted: bool,
    ) -> WorkflowVersion:
        if environment == Environment.PROD.value and require_promoted:
            promotion = session.execute(
                select(Promotion)
                .where(
                    Promotion.workflow_id == workflow.id,
                    Promotion.to_environment == Environment.PROD.value,
                    Promotion.status == PromotionStatus.APPROVED.value,
                )
                .order_by(Promotion.decided_at.desc(), Promotion.version.desc())
                .limit(1)
            ).scalar_one_or_none()
            if promotion is None:
                raise Forbidden(f"workflow {workflow.name!r} has no promoted version for prod")
            if version_number is not None and promotion.version < version_number:
                raise Forbidden(
                    f"version {version_number} is not promoted to prod "
                    f"(approved: {promotion.version})"
                )
            version_number = promotion.version
        query = select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow.id)
        if version_number is not None:
            query = query.where(WorkflowVersion.version == version_number)
        row = session.execute(
            query.order_by(WorkflowVersion.version.desc()).limit(1)
        ).scalar_one_or_none()
        if row is None:
            raise NotFound(
                f"workflow {workflow.name!r} has no version "
                + (str(version_number) if version_number else "")
            )
        return row

    def _active_duplicate(self, session: Session, workflow_id: str, key: str) -> Run | None:
        return session.execute(
            select(Run)
            .where(
                Run.workflow_id == workflow_id,
                Run.duplicate_key == key,
                Run.status.in_(ACTIVE_RUN_STATUSES),
            )
            .order_by(Run.created_at)
            .limit(1)
        ).scalar_one_or_none()

    @staticmethod
    def _duplicate_key(definition: WorkflowDefinition, inputs: dict[str, Any]) -> str:
        key = definition.settings.duplicate_guard_key or "workflow"
        if key in {"workflow", "", "name"}:
            return "workflow"
        path = key[len("inputs.") :] if key.startswith("inputs.") else key
        current: Any = {"inputs": inputs}
        try:
            for part in path.split("."):
                current = current[part] if isinstance(current, dict) else getattr(current, part)
        except (KeyError, AttributeError, TypeError):
            return "workflow"
        return str(current)[:200] if current is not None else "workflow"

    # ------------------------------------------------------------------- tick
    def tick(self) -> int:
        """Advance every active run. Returns the number of runs examined."""
        advanced = 0
        with self.database.session() as session:
            runs = list(
                session.execute(
                    select(Run)
                    .where(Run.status.in_([RunStatus.PENDING.value, RunStatus.RUNNING.value]))
                    .order_by(Run.created_at)
                    .limit(200)
                ).scalars()
            )
            for run in runs:
                try:
                    if self._is_queued(session, run):
                        continue
                    definition = self._definition(session, run)
                    self._advance(session, run, definition)
                    advanced += 1
                except Exception as exc:
                    self.log.error(
                        "engine_tick_failed",
                        run_id=run.id,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    self._record_incident(
                        session,
                        run,
                        None,
                        "engine_error",
                        f"{type(exc).__name__}: {exc}",
                        fault=True,
                    )
        return advanced

    def _is_queued(self, session: Session, run: Run) -> bool:
        if not run.trigger_detail.get("queued"):
            return False
        earlier = session.execute(
            select(Run)
            .where(
                Run.workflow_id == run.workflow_id,
                Run.duplicate_key == run.duplicate_key,
                Run.status.in_(ACTIVE_RUN_STATUSES),
                Run.id != run.id,
                Run.created_at <= run.created_at,
            )
            .limit(1)
        ).scalar_one_or_none()
        if earlier is None:
            run.trigger_detail = {**run.trigger_detail, "queued": False}
            run.status = RunStatus.RUNNING.value
            return False
        return True

    def _definition(self, session: Session, run: Run) -> WorkflowDefinition:
        version = session.get(WorkflowVersion, run.version_id)
        if version is None:
            raise NotFound(f"run {run.id} references a missing workflow version")
        return WorkflowDefinition.model_validate(version.definition)

    # -------------------------------------------------------------- advancing
    def _advance(
        self, session: Session, run: Run, definition: WorkflowDefinition, depth: int = 0
    ) -> None:
        if run.status in TERMINAL_RUN_STATUSES or run.status == RunStatus.SUSPENDED.value:
            return
        if depth > 100:
            self._finish_run(session, run, Outcome.FAILED, {}, "routing loop detected")
            return
        step_id = run.current_step or definition.start_step.id
        run.current_step = step_id
        step = definition.step_map.get(step_id)
        if step is None:
            self._finish_run(session, run, Outcome.FAILED, {}, f"unknown step {step_id!r}")
            return
        rows = list(
            session.execute(
                select(RunStep)
                .where(RunStep.run_id == run.id, RunStep.step_id == step.id)
                .order_by(RunStep.iteration)
            ).scalars()
        )
        if not rows:
            row = self._new_row(session, run, step, 0)
            self._dispatch(session, run, definition, step, row)
            if row.state == StepState.DONE.value:
                self._advance(session, run, definition, depth + 1)
            return
        latest = rows[-1]
        if latest.state == StepState.DISPATCHED.value:
            self._check_watchdog(session, run, definition, step, latest)
            return
        if latest.state == StepState.WAITING.value:
            self._resume_waiting(session, run, definition, step, latest)
            return
        if latest.state == StepState.PENDING.value:
            next_at = latest.next_attempt_at
            if next_at is not None and next_at > self.clock.now():
                return
            if step.foreach and latest.foreach_count <= latest.iteration:
                latest.state = StepState.DONE.value
                latest.outcome = Outcome.DONE.value
                latest.outputs = {"items": self._foreach_items(session, run, step)}
                latest.finished_at = self.clock.now()
                latest.message = "empty foreach collection"
                self._advance(session, run, definition, depth + 1)
                return
            self._dispatch(session, run, definition, step, latest)
            return
        if latest.state == StepState.DONE.value:
            if step.foreach and latest.iteration + 1 < latest.foreach_count:
                next_row = self._new_row(session, run, step, latest.iteration + 1)
                next_row.foreach_count = latest.foreach_count
                self._dispatch(session, run, definition, step, next_row)
                return
            if step.foreach:
                latest.outputs = {"items": self._foreach_items(session, run, step)}
            self._route(session, run, definition, step, Outcome.DONE, latest)
            if run.status in TERMINAL_RUN_STATUSES or run.status == RunStatus.SUSPENDED.value:
                return
            self._advance(session, run, definition, depth + 1)
            return
        if latest.state == StepState.SKIPPED.value:
            self._route(session, run, definition, step, Outcome.DONE, latest)
            self._advance(session, run, definition, depth + 1)
            return
        if latest.state == StepState.FAILED.value:
            self._route(session, run, definition, step, Outcome.FAILED, latest)
            if run.status in TERMINAL_RUN_STATUSES:
                return
            self._advance(session, run, definition, depth + 1)

    def _new_row(self, session: Session, run: Run, step: Step, iteration: int) -> RunStep:
        row = RunStep(
            run_id=run.id,
            step_id=step.id,
            activity=step.activity or "sub_workflow",
            iteration=iteration,
            state=StepState.PENDING.value,
            inputs={},
            outputs={},
        )
        session.add(row)
        session.flush()
        return row

    def _dispatch(
        self,
        session: Session,
        run: Run,
        definition: WorkflowDefinition,
        step: Step,
        row: RunStep,
    ) -> None:
        context = self._resolve_context(session, run, definition)
        try:
            foreach_count = 0
            if step.foreach:
                collection = resolve_value(step.foreach, context)
                if not isinstance(collection, list):
                    raise ReferenceError(
                        f"foreach must resolve to a list, got {type(collection).__name__}"
                    )
                foreach_count = len(collection)
                row.foreach_count = foreach_count
                if row.iteration < len(collection):
                    context.inputs[step.foreach_item] = collection[row.iteration]
            resolved = resolve_value(step.inputs, context)
            if not isinstance(resolved, dict):
                raise ReferenceError("step inputs must resolve to an object")
            inputs = dict(resolved)
        except ReferenceError as exc:
            self._record_incident(session, run, row, "bad_reference", str(exc), fault=True)
            return

        row.inputs = self._persist_inputs(definition, step, inputs)
        row.attempt += 1
        row.started_at = self.clock.now()

        if step.foreach and row.iteration >= row.foreach_count:
            row.state = StepState.DONE.value
            row.outcome = Outcome.DONE.value
            row.outputs = {"items": []}
            row.message = "empty foreach collection"
            row.finished_at = self.clock.now()
            row.duration_ms = 0
            return

        if step.workflow is not None:
            self._start_subworkflow(session, run, step, row, inputs)
            return
        if step.activity == "human_task":
            self._start_human_task(session, run, step, row, inputs)
            return

        row.state = StepState.DISPATCHED.value
        row.next_attempt_at = None
        envelope = JobEnvelope(
            run_id=run.id,
            step_id=step.id,
            iteration=row.iteration,
            activity=step.activity or "",
            inputs=inputs,
            secret_refs=secret_refs(inputs),
            workspace=run.workspace,
            correlation_id=run.correlation_id,
            timeout_seconds=step.timeout_seconds or self.default_timeout_seconds,
        )
        self.bus.enqueue_in(
            session,
            envelope.model_dump(mode="json"),
            max_attempts=step.retries.count + 2,
        )
        run.updated_at = self.clock.now()
        self.audit.write(
            session,
            actor=run.requested_by or "system",
            action="run.step.dispatch",
            resource_type="run",
            resource_id=run.id,
            after={
                "step": step.id,
                "iteration": row.iteration,
                "attempt": row.attempt,
                "activity": step.activity,
            },
            correlation_id=run.correlation_id,
        )

    def _start_subworkflow(
        self,
        session: Session,
        run: Run,
        step: Step,
        row: RunStep,
        inputs: dict[str, Any],
    ) -> None:
        assert step.workflow is not None
        child_workflow = session.execute(
            select(Workflow).where(Workflow.name == step.workflow.name)
        ).scalar_one_or_none()
        if child_workflow is None:
            self._record_incident(
                session,
                run,
                row,
                "subworkflow_missing",
                f"unknown workflow {step.workflow.name!r}",
                True,
            )
            return
        child_version = session.execute(
            select(WorkflowVersion).where(
                WorkflowVersion.workflow_id == child_workflow.id,
                WorkflowVersion.version == step.workflow.version,
            )
        ).scalar_one_or_none()
        if child_version is None:
            self._record_incident(
                session,
                run,
                row,
                "subworkflow_version_missing",
                f"{step.workflow.name}@{step.workflow.version} not found",
                True,
            )
            return
        if run.environment == Environment.PROD.value:
            promoted = session.execute(
                select(Promotion).where(
                    Promotion.workflow_id == child_workflow.id,
                    Promotion.version == child_version.version,
                    Promotion.to_environment == Environment.PROD.value,
                    Promotion.status == PromotionStatus.APPROVED.value,
                )
            ).scalar_one_or_none()
            if promoted is None:
                self._record_incident(
                    session,
                    run,
                    row,
                    "subworkflow_not_promoted",
                    f"{step.workflow.name}@{step.workflow.version} is not promoted to prod",
                    True,
                )
                return
        child = Run(
            workflow_id=child_workflow.id,
            workflow_name=child_workflow.name,
            version_id=child_version.id,
            version=child_version.version,
            environment=run.environment,
            status=RunStatus.RUNNING.value,
            trigger="subworkflow",
            trigger_detail={"parent_run_id": run.id, "step_id": step.id},
            correlation_id=run.correlation_id,
            workspace="",
            current_step=WorkflowDefinition.model_validate(child_version.definition).start_step.id,
            inputs=inputs,
            requested_by=run.requested_by,
            duplicate_key="subworkflow",
            parent_run_id=run.id,
            created_at=self.clock.now(),
            started_at=self.clock.now(),
            updated_at=self.clock.now(),
        )
        session.add(child)
        session.flush()
        child_workspace = self.workspaces / child.id
        child_workspace.mkdir(parents=True, exist_ok=True)
        child.workspace = str(child_workspace)
        row.state = StepState.WAITING.value
        row.child_run_id = child.id
        self.audit.write(
            session,
            actor=run.requested_by or "system",
            action="run.child.start",
            resource_type="run",
            resource_id=child.id,
            after={"parent": run.id, "step": step.id, "workflow": child_workflow.name},
            correlation_id=run.correlation_id,
        )
        self._advance(
            session,
            child,
            WorkflowDefinition.model_validate(child_version.definition),
        )

    def _start_human_task(
        self,
        session: Session,
        run: Run,
        step: Step,
        row: RunStep,
        inputs: dict[str, Any],
    ) -> None:
        masker = get_masker()
        task_type = str(inputs.get("type", "approval"))
        title = str(inputs.get("title", f"{run.workflow_name}: {step.id}"))[:255]
        due_minutes = int(inputs.get("due_minutes", 60) or 60)
        task = Task(
            run_id=run.id,
            step_id=step.id,
            type=task_type,
            title=masker.mask(title),
            description=masker.mask_obj(str(inputs.get("description", "")))[:4000],
            assignee_role=str(inputs.get("assignee_role", "operator")),
            status="open",
            priority=int(inputs.get("priority", 2) or 2),
            payload=inputs.get("payload", {}) if isinstance(inputs.get("payload"), dict) else {},
            due_at=self.clock.now() + timedelta(minutes=due_minutes),
            created_at=self.clock.now(),
        )
        session.add(task)
        session.flush()
        session.add(
            ResumeToken(
                run_id=run.id,
                step_id=step.id,
                token=f"{run.id}-{step.id}-{row.iteration}-{task.id}",
                payload={"task_id": task.id, "iteration": row.iteration},
                created_at=self.clock.now(),
            )
        )
        row.state = StepState.WAITING.value
        run.status = RunStatus.SUSPENDED.value
        run.updated_at = self.clock.now()
        self.audit.write(
            session,
            actor=run.requested_by or "system",
            action="run.suspend",
            resource_type="run",
            resource_id=run.id,
            after={"step": step.id, "task_id": task.id, "task_type": task_type},
            correlation_id=run.correlation_id,
        )

    def _resume_waiting(
        self,
        session: Session,
        run: Run,
        definition: WorkflowDefinition,
        step: Step,
        row: RunStep,
    ) -> None:
        if row.child_run_id:
            child = session.get(Run, row.child_run_id)
            if child is None:
                self._record_incident(
                    session, run, row, "child_missing", "child run not found", True
                )
                return
            if child.status not in TERMINAL_RUN_STATUSES:
                return
            outcome = Outcome.DONE if child.status == RunStatus.DONE.value else Outcome.FAILED
            self._complete_step(
                session,
                run,
                definition,
                step,
                row,
                outcome,
                child.outputs,
                f"sub-workflow {child.workflow_name} finished {child.status}",
                [],
                allow_retry=False,
            )
            self._advance(session, run, definition)
            return
        token = session.execute(
            select(ResumeToken)
            .where(
                ResumeToken.run_id == run.id,
                ResumeToken.step_id == step.id,
                ResumeToken.consumed_at.is_(None),
            )
            .order_by(ResumeToken.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if token is None:
            return

    # ------------------------------------------------------------- completion
    def on_result(self, envelope: JobEnvelope, result: ResultEnvelope) -> None:
        with self.database.session() as session:
            run = session.get(Run, envelope.run_id)
            if run is None or run.status in TERMINAL_RUN_STATUSES:
                return
            row = session.execute(
                select(RunStep).where(
                    RunStep.run_id == envelope.run_id,
                    RunStep.step_id == envelope.step_id,
                    RunStep.iteration == envelope.iteration,
                )
            ).scalar_one_or_none()
            if row is None or row.state != StepState.DISPATCHED.value:
                self.log.info(
                    "stale_result_ignored",
                    run_id=envelope.run_id,
                    step_id=envelope.step_id,
                )
                return
            definition = self._definition(session, run)
            step = definition.step_map.get(envelope.step_id)
            if step is None:
                return
            outcome = Outcome(result.outcome)
            self._complete_step(
                session,
                run,
                definition,
                step,
                row,
                outcome,
                result.outputs,
                result.message,
                [artifact.model_dump() for artifact in result.artifacts],
                allow_retry=outcome is Outcome.FAILED,
            )
            self._advance(session, run, definition)
            self._emit(
                {
                    "type": "step.completed",
                    "run_id": envelope.run_id,
                    "step_id": envelope.step_id,
                    "outcome": result.outcome,
                    "message": get_masker().mask(result.message),
                }
            )

    def _complete_step(
        self,
        session: Session,
        run: Run,
        definition: WorkflowDefinition,
        step: Step,
        row: RunStep,
        outcome: Outcome,
        outputs: dict[str, Any],
        message: str,
        artifacts: list[dict[str, Any]],
        *,
        allow_retry: bool,
    ) -> None:
        now = self.clock.now()
        duration_ms = 0
        if row.started_at is not None:
            duration_ms = max(0, int((now - row.started_at).total_seconds() * 1000))
        row.state = StepState.DONE.value if outcome is Outcome.DONE else StepState.FAILED.value
        row.outcome = outcome.value
        row.finished_at = now
        row.duration_ms = duration_ms
        row.message = get_masker().mask(message)[:4000]
        row.outputs = self._persist_outputs(definition, step, outputs)
        row.artifacts = artifacts
        session.add(
            StepAttempt(
                run_id=run.id,
                step_id=step.id,
                iteration=row.iteration,
                attempt=row.attempt,
                outcome=outcome.value,
                message=row.message,
                started_at=row.started_at or now,
                finished_at=now,
                duration_ms=duration_ms,
            )
        )
        for artifact in artifacts:
            session.add(
                Artifact(
                    run_id=run.id,
                    step_id=step.id,
                    name=str(artifact.get("name", ""))[:255],
                    path=str(artifact.get("path", ""))[:1000],
                    sha256=str(artifact.get("sha256", ""))[:64],
                    bytes=int(artifact.get("bytes", 0) or 0),
                    created_at=now,
                )
            )
        self.audit.write(
            session,
            actor=run.requested_by or "system",
            action=f"run.step.{outcome.value}",
            resource_type="run",
            resource_id=run.id,
            after={
                "step": step.id,
                "iteration": row.iteration,
                "attempt": row.attempt,
                "duration_ms": duration_ms,
            },
            correlation_id=run.correlation_id,
        )
        run.updated_at = now

        if outcome is Outcome.FAILED and allow_retry and row.attempt <= step.retries.count:
            delay = step.retries.delay_seconds * (step.retries.backoff ** max(0, row.attempt - 1))
            row.state = StepState.PENDING.value
            row.next_attempt_at = now + timedelta(seconds=delay)
            run.status = RunStatus.RUNNING.value
            self.audit.write(
                session,
                actor=run.requested_by or "system",
                action="run.step.retry",
                resource_type="run",
                resource_id=run.id,
                after={"step": step.id, "attempt": row.attempt, "delay_seconds": delay},
                correlation_id=run.correlation_id,
            )

    def _route(
        self,
        session: Session,
        run: Run,
        definition: WorkflowDefinition,
        step: Step,
        outcome: Outcome,
        row: RunStep,
    ) -> None:
        target = step.on_done if outcome is Outcome.DONE else step.on_failed
        if target and target in definition.step_map:
            run.current_step = target
            run.updated_at = self.clock.now()
            self.audit.write(
                session,
                actor=run.requested_by or "system",
                action="run.route",
                resource_type="run",
                resource_id=run.id,
                after={"from": step.id, "outcome": outcome.value, "to": target},
                correlation_id=run.correlation_id,
            )
            return
        if outcome is Outcome.DONE:
            self._finish_run(session, run, Outcome.DONE, row.outputs, "")
        else:
            self._finish_run(
                session,
                run,
                Outcome.FAILED,
                row.outputs,
                row.message or f"step {step.id} failed",
            )

    def _finish_run(
        self,
        session: Session,
        run: Run,
        outcome: Outcome,
        outputs: dict[str, Any],
        error: str,
    ) -> None:
        run.status = RunStatus.DONE.value if outcome is Outcome.DONE else RunStatus.FAILED.value
        run.finished_at = self.clock.now()
        run.updated_at = self.clock.now()
        run.outputs = outputs
        run.error = get_masker().mask(error)[:4000]
        self.audit.write(
            session,
            actor=run.requested_by or "system",
            action="run.finish",
            resource_type="run",
            resource_id=run.id,
            after={"status": run.status, "error": run.error},
            correlation_id=run.correlation_id,
        )
        self.log.info(
            "run_finished",
            run_id=run.id,
            workflow=run.workflow_name,
            status=run.status,
        )
        self._emit(
            {
                "type": "run.finished",
                "run_id": run.id,
                "workflow": run.workflow_name,
                "status": run.status,
            }
        )

    def _record_incident(
        self,
        session: Session,
        run: Run,
        row: RunStep | None,
        kind: str,
        message: str,
        fault: bool,
    ) -> None:
        session.add(
            Incident(
                run_id=run.id,
                step_id=row.step_id if row else None,
                kind=kind,
                message=get_masker().mask(message)[:4000],
                created_at=self.clock.now(),
            )
        )
        if fault:
            run.status = RunStatus.FAILED.value
            run.finished_at = self.clock.now()
            run.error = get_masker().mask(message)[:4000]
            self.audit.write(
                session,
                actor=run.requested_by or "system",
                action="run.finish",
                resource_type="run",
                resource_id=run.id,
                after={"status": RunStatus.FAILED.value, "incident": kind},
                correlation_id=run.correlation_id,
            )

    # ------------------------------------------------------------------ tasks
    def complete_human_task(
        self, run_id: str, task_id: str, *, session: Session | None = None
    ) -> None:
        if session is not None:
            self._complete_human_task(session, run_id, task_id)
            return
        with self.database.session() as own_session:
            self._complete_human_task(own_session, run_id, task_id)

    def _complete_human_task(self, session: Session, run_id: str, task_id: str) -> None:
        run = session.get(Run, run_id)
        task = session.get(Task, task_id)
        if run is None or task is None:
            raise NotFound("run or task not found")
        if run.status != RunStatus.SUSPENDED.value:
            return
        token = session.execute(
            select(ResumeToken)
            .where(
                ResumeToken.run_id == run_id,
                ResumeToken.consumed_at.is_(None),
            )
            .order_by(ResumeToken.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if token is None:
            raise Conflict("run has no open resume token")
        definition = self._definition(session, run)
        step = definition.step_map.get(token.step_id)
        if step is None:
            raise NotFound("suspended step no longer exists")
        row = session.execute(
            select(RunStep).where(
                RunStep.run_id == run_id,
                RunStep.step_id == token.step_id,
                RunStep.iteration == int(token.payload.get("iteration", 0)),
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFound("suspended step row not found")
        token.consumed_at = self.clock.now()
        run.status = RunStatus.RUNNING.value
        outcome = Outcome.FAILED if task.decision == "reject" else Outcome.DONE
        self.audit.write(
            session,
            actor=task.claimed_by or "system",
            action="run.resume",
            resource_type="run",
            resource_id=run.id,
            after={"task_id": task.id, "decision": task.decision},
            correlation_id=run.correlation_id,
        )
        self._complete_step(
            session,
            run,
            definition,
            step,
            row,
            outcome,
            {"decision": task.decision, "reason": task.reason, **task.result},
            task.reason or f"task {task.type} completed",
            [],
            allow_retry=False,
        )
        self._advance(session, run, definition)

    # ---------------------------------------------------------------- helpers
    def _resolve_context(
        self, session: Session, run: Run, definition: WorkflowDefinition
    ) -> ResolveContext:
        rows = list(
            session.execute(
                select(RunStep)
                .where(RunStep.run_id == run.id, RunStep.state == StepState.DONE.value)
                .order_by(RunStep.iteration)
            ).scalars()
        )
        steps: dict[str, Any] = {}
        for row in rows:
            step = definition.step_map.get(row.step_id)
            outputs = dict(row.outputs)
            if step is not None and step.foreach:
                outputs["items"] = self._foreach_items(session, run, step)
            steps[row.step_id] = outputs
        return ResolveContext(
            steps=steps,
            inputs=run.inputs,
            run_id=run.id,
            run={
                "id": run.id,
                "correlation_id": run.correlation_id,
                "environment": run.environment,
                "workspace": run.workspace,
            },
        )

    def _foreach_items(self, session: Session, run: Run, step: Step) -> list[Any]:
        rows = session.execute(
            select(RunStep)
            .where(
                RunStep.run_id == run.id,
                RunStep.step_id == step.id,
                RunStep.state == StepState.DONE.value,
            )
            .order_by(RunStep.iteration)
        ).scalars()
        return [row.outputs for row in rows]

    def _persist_inputs(
        self, definition: WorkflowDefinition, step: Step, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        if definition.settings.persistence == "none" or step.persist == "exclude":
            return {}
        activity = self.registry.get(step.activity) if step.activity else None
        redacted = dict(inputs)
        if activity is not None:
            for field in activity.sensitive_fields:
                if field in redacted:
                    redacted[field] = "***"
        serialized = json.dumps(redacted, default=str)
        if len(serialized) > self.max_persisted_output_bytes:
            return {"_omitted": f"{len(serialized)} bytes of inputs not persisted"}
        return redacted

    def _persist_outputs(
        self, definition: WorkflowDefinition, step: Step, outputs: dict[str, Any]
    ) -> dict[str, Any]:
        if definition.settings.persistence == "none" or step.persist == "exclude":
            return {}
        masked = get_masker().mask_obj(outputs)
        serialized = json.dumps(masked, default=str)
        if len(serialized) > self.max_persisted_output_bytes:
            return {"_omitted": f"{len(serialized)} bytes of outputs not persisted"}
        return dict(masked) if isinstance(masked, dict) else {"value": masked}

    def _check_watchdog(
        self,
        session: Session,
        run: Run,
        definition: WorkflowDefinition,
        step: Step,
        row: RunStep,
    ) -> None:
        if row.started_at is None:
            return
        deadline = row.started_at + timedelta(
            seconds=(step.timeout_seconds or self.default_timeout_seconds) + 120
        )
        if self.clock.now() < deadline:
            return
        self._complete_step(
            session,
            run,
            definition,
            step,
            row,
            Outcome.FAILED,
            {},
            f"step {step.id} exceeded its timeout and was reset",
            [],
            allow_retry=True,
        )
        self._advance(session, run, definition)

    # --------------------------------------------------------------- recovery
    def recover(self) -> int:
        """Requeue in-flight steps after a restart. Returns the number of runs touched."""
        recovered = 0
        with self.database.session() as session:
            runs = list(
                session.execute(
                    select(Run).where(
                        Run.status.in_([RunStatus.PENDING.value, RunStatus.RUNNING.value])
                    )
                ).scalars()
            )
            for run in runs:
                rows = list(
                    session.execute(
                        select(RunStep).where(
                            RunStep.run_id == run.id,
                            RunStep.state == StepState.DISPATCHED.value,
                        )
                    ).scalars()
                )
                definition = self._definition(session, run)
                for row in rows:
                    step = definition.step_map.get(row.step_id)
                    if step is not None and step.resume.value == "skip" and row.attempt > 0:
                        row.state = StepState.DONE.value
                        row.outcome = Outcome.DONE.value
                        row.message = "skipped on resume"
                        row.finished_at = self.clock.now()
                    else:
                        row.state = StepState.PENDING.value
                        row.next_attempt_at = None
                    recovered += 1
                    self.audit.write(
                        session,
                        actor="system",
                        action="run.resume.recover",
                        resource_type="run",
                        resource_id=run.id,
                        after={
                            "step": row.step_id,
                            "mode": step.resume.value if step else "restart",
                        },
                        correlation_id=run.correlation_id,
                    )
                if run.status == RunStatus.PENDING.value:
                    run.status = RunStatus.RUNNING.value
            return recovered
