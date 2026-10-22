"""Schedules: cron, webhook, file arrival, dependency, manual, and duplicate handling."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.db.database import Database
from app.adapters.db.models import ProcessedFile, Run, Schedule, Workflow, WorkflowVersion
from app.audit.writer import AuditWriter
from app.domain.clock import Clock
from app.domain.enums import Environment, TriggerKind
from app.engine.run_engine import RunEngine
from app.errors import DuplicateRun, NotFound, ValidationFailed
from app.logging_setup import get_logger

# A cron fire that is this late (the service was down or busy) counts as missed and is
# skipped unless the schedule or workflow asks for catch-up.
DEFAULT_MISFIRE_GRACE_SECONDS = 60


@dataclass(frozen=True)
class TriggerAction:
    schedule_id: str
    workflow_id: str
    environment: str
    inputs: dict[str, Any]
    trigger: str
    detail: dict[str, Any]


class ScheduleService:
    def __init__(self, clock: Clock, audit: AuditWriter) -> None:
        self.clock = clock
        self.audit = audit

    def create(
        self,
        session: Session,
        *,
        workflow_id: str,
        kind: str,
        name: str = "",
        cron: str = "",
        timezone: str = "UTC",
        config: dict[str, Any] | None = None,
        environment: str = Environment.DEV.value,
        created_by: str = "",
        correlation_id: str = "",
        source_ip: str = "",
    ) -> Schedule:
        workflow = session.get(Workflow, workflow_id)
        if workflow is None:
            raise NotFound(f"workflow {workflow_id} not found")
        if kind not in {item.value for item in TriggerKind if item is not TriggerKind.MANUAL}:
            raise ValidationFailed(f"unsupported trigger kind {kind!r}")
        if kind == TriggerKind.CRON.value:
            validate_cron(cron)
            if not name:
                name = f"{workflow.name} {cron}"
        token = secrets.token_urlsafe(24) if kind == TriggerKind.WEBHOOK.value else None
        schedule = Schedule(
            workflow_id=workflow.id,
            kind=kind,
            name=name or f"{workflow.name} {kind}",
            cron=cron,
            timezone=timezone,
            enabled=True,
            config=config or {},
            token=token,
            environment=environment,
            next_run_at=None,
            created_by=created_by,
            created_at=self.clock.now(),
        )
        session.add(schedule)
        session.flush()
        self.audit.write(
            session,
            actor=created_by or "system",
            action="schedule.create",
            resource_type="schedule",
            resource_id=schedule.id,
            source_ip=source_ip,
            after={
                "workflow": workflow.name,
                "kind": kind,
                "cron": cron,
                "environment": environment,
            },
            correlation_id=correlation_id,
        )
        return schedule

    def list(self, session: Session, workflow_id: str | None = None) -> list[Schedule]:
        query = select(Schedule).order_by(Schedule.created_at.desc())
        if workflow_id:
            query = query.where(Schedule.workflow_id == workflow_id)
        return list(session.execute(query).scalars())

    def enable(
        self,
        session: Session,
        schedule_id: str,
        enabled: bool,
        *,
        actor: str,
        correlation_id: str = "",
        source_ip: str = "",
    ) -> Schedule:
        schedule = session.get(Schedule, schedule_id)
        if schedule is None:
            raise NotFound("schedule not found")
        before = schedule.enabled
        schedule.enabled = enabled
        schedule.next_run_at = None
        self.audit.write(
            session,
            actor=actor,
            action="schedule.enable" if enabled else "schedule.disable",
            resource_type="schedule",
            resource_id=schedule.id,
            source_ip=source_ip,
            before={"enabled": before},
            after={"enabled": enabled},
            correlation_id=correlation_id,
        )
        return schedule

    def delete(
        self,
        session: Session,
        schedule_id: str,
        *,
        actor: str,
        correlation_id: str = "",
        source_ip: str = "",
    ) -> None:
        schedule = session.get(Schedule, schedule_id)
        if schedule is None:
            raise NotFound("schedule not found")
        session.delete(schedule)
        self.audit.write(
            session,
            actor=actor,
            action="schedule.delete",
            resource_type="schedule",
            resource_id=schedule_id,
            source_ip=source_ip,
            correlation_id=correlation_id,
        )


def validate_cron(expression: str) -> None:
    try:
        CronTrigger.from_crontab(expression)
    except (ValueError, TypeError) as exc:
        raise ValidationFailed(f"invalid cron expression {expression!r}: {exc}") from exc


def next_cron_fire(expression: str, timezone: str, after: datetime) -> datetime:
    """The first fire time strictly after ``after``.

    APScheduler's lookup is inclusive, so passing a fire time back in would return the same
    instant and fire it forever; start from the next whole second instead.
    """
    trigger = CronTrigger.from_crontab(expression, timezone=ZoneInfo(timezone))
    start = after.replace(microsecond=0) + timedelta(seconds=1)
    fire = trigger.get_next_fire_time(None, start)
    if fire is None:  # pragma: no cover - crontab always has a next fire
        raise ValidationFailed(f"cron expression {expression!r} never fires")
    return datetime(fire.year, fire.month, fire.day, fire.hour, fire.minute, tzinfo=fire.tzinfo)


class TriggerService:
    """Evaluates cron, file, dependency and webhook triggers. Safe to call repeatedly."""

    def __init__(
        self,
        *,
        database: Database,
        clock: Clock,
        audit: AuditWriter,
        engine: RunEngine,
        data_root: Path,
        file_watch_enabled: bool = True,
    ) -> None:
        self.database = database
        self.clock = clock
        self.audit = audit
        self.engine = engine
        self.data_root = data_root
        self.file_watch_enabled = file_watch_enabled
        self.log = get_logger(__name__)

    def tick(self) -> list[str]:
        actions: list[TriggerAction] = []
        actions.extend(self._cron_actions())
        if self.file_watch_enabled:
            actions.extend(self._file_actions())
        actions.extend(self._dependency_actions())
        started: list[str] = []
        for action in actions:
            try:
                run = self.engine.start_run(
                    workflow_id=action.workflow_id,
                    environment=action.environment,
                    trigger=action.trigger,
                    requested_by="scheduler",
                    inputs=action.inputs,
                    trigger_detail=action.detail,
                    correlation_id=f"{action.schedule_id}-{int(self.clock.now().timestamp())}",
                )
                started.append(run.id)
            except DuplicateRun as exc:
                self.log.info("trigger_suppressed", schedule_id=action.schedule_id, reason=str(exc))
                if action.trigger == "file":
                    # The file was not processed: forget it so a later tick picks it up again.
                    self._forget_file(action)
            except Exception as exc:
                self.log.error(
                    "trigger_failed",
                    schedule_id=action.schedule_id,
                    error=f"{type(exc).__name__}: {exc}",
                )
        return started

    def _cron_actions(self) -> list[TriggerAction]:
        actions: list[TriggerAction] = []
        now = self.clock.now()
        with self.database.session() as session:
            schedules = list(
                session.execute(
                    select(Schedule).where(Schedule.enabled.is_(True), Schedule.kind == "cron")
                ).scalars()
            )
            for schedule in schedules:
                catch_up = self._catch_up(session, schedule)
                if schedule.next_run_at is None:
                    schedule.next_run_at = next_cron_fire(
                        schedule.cron, schedule.timezone or "UTC", now
                    )
                    continue
                if schedule.next_run_at > now:
                    continue
                grace = int(
                    schedule.config.get("misfire_grace_seconds", DEFAULT_MISFIRE_GRACE_SECONDS)
                )
                lateness = (now - schedule.next_run_at).total_seconds()
                if not catch_up and lateness > grace:
                    self.audit.write(
                        session,
                        actor="scheduler",
                        action="schedule.missed",
                        resource_type="schedule",
                        resource_id=schedule.id,
                        after={
                            "scheduled_for": schedule.next_run_at.isoformat(),
                            "late_seconds": int(lateness),
                        },
                    )
                    schedule.next_run_at = next_cron_fire(
                        schedule.cron, schedule.timezone or "UTC", now
                    )
                    continue
                actions.append(
                    TriggerAction(
                        schedule_id=schedule.id,
                        workflow_id=schedule.workflow_id,
                        environment=schedule.environment,
                        inputs=dict(schedule.config.get("inputs", {})),
                        trigger="cron",
                        detail={
                            "schedule_id": schedule.id,
                            "scheduled_for": schedule.next_run_at.isoformat(),
                        },
                    )
                )
                schedule.last_run_at = now
                if catch_up:
                    schedule.next_run_at = next_cron_fire(
                        schedule.cron, schedule.timezone or "UTC", schedule.next_run_at
                    )
                else:
                    schedule.next_run_at = next_cron_fire(
                        schedule.cron, schedule.timezone or "UTC", now
                    )
        return actions

    @staticmethod
    def _catch_up(session: Session, schedule: Schedule) -> bool:
        """Schedule config wins; otherwise the workflow's latest ``settings.catch_up``."""
        if "catch_up" in schedule.config:
            return bool(schedule.config["catch_up"])
        version = session.execute(
            select(WorkflowVersion)
            .where(WorkflowVersion.workflow_id == schedule.workflow_id)
            .order_by(WorkflowVersion.version.desc())
            .limit(1)
        ).scalar_one_or_none()
        if version is None:
            return False
        return bool((version.definition.get("settings") or {}).get("catch_up", False))

    def _file_actions(self) -> list[TriggerAction]:
        actions: list[TriggerAction] = []
        now = self.clock.now()
        with self.database.session() as session:
            schedules = list(
                session.execute(
                    select(Schedule).where(Schedule.enabled.is_(True), Schedule.kind == "file")
                ).scalars()
            )
            for schedule in schedules:
                folder = Path(str(schedule.config.get("path", "")))
                if not folder.is_absolute():
                    folder = self.data_root / folder
                if not folder.exists() or not folder.is_dir():
                    continue
                pattern = str(schedule.config.get("pattern", "*"))
                settle = int(schedule.config.get("settle_seconds", 10))
                recursive = bool(schedule.config.get("recursive", False))
                candidates = folder.rglob(pattern) if recursive else folder.glob(pattern)
                for path in candidates:
                    if not path.is_file():
                        continue
                    try:
                        mtime = path.stat().st_mtime
                    except OSError:
                        continue
                    if now.timestamp() - mtime < settle:
                        continue
                    digest = _sha256(path)
                    already = session.execute(
                        select(ProcessedFile.id).where(
                            ProcessedFile.schedule_id == schedule.id,
                            ProcessedFile.path == str(path),
                            ProcessedFile.sha256 == digest,
                        )
                    ).first()
                    if already:
                        continue
                    session.add(
                        ProcessedFile(
                            schedule_id=schedule.id,
                            path=str(path)[:1000],
                            sha256=digest,
                            processed_at=now,
                        )
                    )
                    inputs = dict(schedule.config.get("inputs", {}))
                    inputs.setdefault("file", str(path))
                    actions.append(
                        TriggerAction(
                            schedule_id=schedule.id,
                            workflow_id=schedule.workflow_id,
                            environment=schedule.environment,
                            inputs=inputs,
                            trigger="file",
                            detail={
                                "schedule_id": schedule.id,
                                "file": str(path),
                                "sha256": digest,
                            },
                        )
                    )
        return actions

    def _dependency_actions(self) -> list[TriggerAction]:
        actions: list[TriggerAction] = []
        with self.database.session() as session:
            finished = list(
                session.execute(
                    select(Run).where(
                        Run.status.in_(["done", "failed"]),
                        Run.dependency_dispatched.is_(False),
                    )
                ).scalars()
            )
            if not finished:
                return []
            schedules = list(
                session.execute(
                    select(Schedule).where(
                        Schedule.enabled.is_(True), Schedule.kind == "dependency"
                    )
                ).scalars()
            )
            for run in finished:
                run.dependency_dispatched = True
                for schedule in schedules:
                    expected_workflow = str(schedule.config.get("workflow", ""))
                    expected_outcome = str(schedule.config.get("outcome", "done"))
                    if expected_workflow not in {run.workflow_name, run.workflow_id}:
                        continue
                    if expected_outcome != run.status:
                        continue
                    actions.append(
                        TriggerAction(
                            schedule_id=schedule.id,
                            workflow_id=schedule.workflow_id,
                            environment=schedule.environment,
                            inputs={
                                **dict(schedule.config.get("inputs", {})),
                                "upstream": {
                                    "run_id": run.id,
                                    "workflow": run.workflow_name,
                                    "status": run.status,
                                    "outputs": run.outputs,
                                },
                            },
                            trigger="dependency",
                            detail={"schedule_id": schedule.id, "upstream_run_id": run.id},
                        )
                    )
        return actions

    def _forget_file(self, action: TriggerAction) -> None:
        with self.database.session() as session:
            for row in session.execute(
                select(ProcessedFile).where(
                    ProcessedFile.schedule_id == action.schedule_id,
                    ProcessedFile.path == str(action.detail.get("file", ""))[:1000],
                    ProcessedFile.sha256 == str(action.detail.get("sha256", "")),
                )
            ).scalars():
                session.delete(row)

    def fire_webhook(self, token: str, payload: dict[str, Any]) -> Run:
        with self.database.session() as session:
            schedule = session.execute(
                select(Schedule).where(
                    Schedule.token == token,
                    Schedule.kind == "webhook",
                    Schedule.enabled.is_(True),
                )
            ).scalar_one_or_none()
            if schedule is None:
                raise NotFound("webhook not found or disabled")
            workflow_id = schedule.workflow_id
            environment = schedule.environment
            inputs = {**dict(schedule.config.get("inputs", {})), **payload}
            schedule_id = schedule.id
        return self.engine.start_run(
            workflow_id=workflow_id,
            environment=environment,
            trigger="webhook",
            requested_by="webhook",
            inputs=inputs,
            trigger_detail={"schedule_id": schedule_id},
            correlation_id=f"webhook-{schedule_id}-{int(self.clock.now().timestamp())}",
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def due_sla(deadline: datetime | None, now: datetime) -> bool:
    return deadline is not None and deadline < now


def schedule_is_active(enabled: bool, next_run: datetime | None, now: datetime) -> bool:
    return enabled and next_run is not None and next_run <= now


def next_after(expression: str, timezone: str, after: datetime) -> datetime:
    return next_cron_fire(expression, timezone, after)


def plus_seconds(value: datetime, seconds: int) -> datetime:
    return value + timedelta(seconds=seconds)
