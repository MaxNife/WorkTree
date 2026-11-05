"""Dependency container and background runtime."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from app.adapters.db.database import Database
from app.adapters.db.models import Environment as EnvironmentRow
from app.adapters.db.models import RoleRow, User, UserRole
from app.adapters.secrets.base import SecretStore
from app.adapters.secrets.local import LocalSecretStore
from app.audit.guard import install_audit_guard
from app.audit.writer import AuditWriter
from app.bus.db_bus import DbMessageBus
from app.config import Settings, load_settings
from app.domain.activity_registry import ActivityRegistry
from app.domain.clock import Clock, SystemClock
from app.domain.enums import Role
from app.engine.run_engine import RunEngine
from app.events import EventHub
from app.logging_setup import get_logger
from app.security.rate_limit import LoginRateLimiter
from app.security.sessions import SessionCodec, SessionFactory
from app.services.auth import AuthService
from app.services.notifications import NotificationService
from app.services.schedules import ScheduleService, TriggerService
from app.services.tasks import TaskService
from app.services.workflows import WorkflowService
from app.workers.process import child_environment
from app.workers.runtime import WorkerPool

REFERENCE_ROLES = {
    Role.VIEWER: "Read dashboards and run history",
    Role.OPERATOR: "Trigger runs and action tasks",
    Role.AUTHOR: "Build workflows in dev and test",
    Role.APPROVER: "Approve decisions and promotions",
    Role.ADMIN: "Administer users, schedules and settings",
}


def make_secret_store(settings: Settings, clock: Clock) -> SecretStore:
    if settings.secrets.adapter == "vault":
        from app.adapters.secrets.vault import VaultSecretStore

        return VaultSecretStore(
            settings.secrets.vault_url,
            os.environ.get(settings.secrets.vault_token_env, ""),
            settings.secrets.vault_mount,
            clock,
        )
    return LocalSecretStore(settings.secrets.file, clock)


def seed_reference_data(database: Database) -> None:
    with database.session() as session:
        existing_roles = set(session.execute(select(RoleRow.name)).scalars())
        for role, description in REFERENCE_ROLES.items():
            if role.value not in existing_roles:
                session.add(RoleRow(name=role.value, description=description))
        existing_envs = set(session.execute(select(EnvironmentRow.name)).scalars())
        for name, is_prod in (("dev", False), ("test", False), ("prod", True)):
            if name not in existing_envs:
                session.add(EnvironmentRow(name=name, is_production=is_prod))


@dataclass
class Container:
    settings: Settings
    clock: Clock
    database: Database
    secrets: SecretStore
    audit: AuditWriter
    bus: DbMessageBus
    registry: ActivityRegistry
    engine: RunEngine
    auth: AuthService
    workflows: WorkflowService
    notifications: NotificationService
    tasks: TaskService
    schedules: ScheduleService
    triggers: TriggerService
    workers: WorkerPool
    events: EventHub
    session_factory: SessionFactory
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def startup(self, *, start_background: bool = True) -> None:
        seed_reference_data(self.database)
        recovered = self.engine.recover()
        if recovered:
            get_logger(__name__).info("runs_recovered", steps=recovered)
        if start_background:
            self.workers.start()
            self._thread = threading.Thread(target=self._loop, name="uaf-scheduler", daemon=True)
            self._thread.start()

    def _loop(self) -> None:  # pragma: no cover - background loop
        while not self._stop.wait(self.settings.scheduler.tick_seconds):
            try:
                self.engine.tick()
                self.triggers.tick()
                with self.database.session() as session:
                    self.tasks.check_sla(session)
            except Exception as exc:
                get_logger(__name__).error(
                    "scheduler_tick_failed", error=f"{type(exc).__name__}: {exc}"
                )

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self.workers.stop()
        self.database.dispose()

    def has_admin(self) -> bool:
        with self.database.session() as session:
            row = session.execute(
                select(User.id)
                .join(UserRole, UserRole.user_id == User.id)
                .join(RoleRow, RoleRow.id == UserRole.role_id)
                .where(RoleRow.name == Role.ADMIN.value, User.is_active.is_(True))
                .limit(1)
            ).first()
            return row is not None


def build_container(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    create_schema: bool = False,
    start: bool = False,
    registry: ActivityRegistry | None = None,
) -> Container:
    settings = settings or load_settings()
    clock = clock or SystemClock()
    install_audit_guard()
    if settings.bus.adapter != "db":
        # The engine enqueues jobs inside its own transaction (an outbox), which a broker cannot
        # join. Refuse rather than silently fall back to the DB bus (DECISIONS 9.12).
        raise ValueError(
            f"bus.adapter {settings.bus.adapter!r} is not available in this build; use 'db'"
        )
    database = Database(settings.database.url, echo=settings.database.echo)
    if create_schema:
        database.create_all()
    secrets = make_secret_store(settings, clock)
    audit = AuditWriter(clock)
    bus = DbMessageBus(
        database,
        clock,
        visibility_timeout_seconds=settings.bus.visibility_timeout_seconds,
        max_attempts=settings.bus.max_attempts,
    )
    activity_registry = registry or ActivityRegistry(settings.activities.extra_folder).discover()
    events = EventHub()
    engine = RunEngine(
        database=database,
        clock=clock,
        audit=audit,
        bus=bus,
        registry=activity_registry,
        workspaces=settings.data.workspaces,
        default_timeout_seconds=settings.workers.default_timeout_seconds,
        event_sink=events.publish,
    )
    session_codec = SessionCodec(secrets)
    session_factory = SessionFactory(session_codec, clock, settings.security.session_ttl_minutes)
    limiter = LoginRateLimiter(
        clock,
        settings.security.login_rate_limit_attempts,
        settings.security.login_rate_limit_window_seconds,
        address_attempts=settings.security.login_rate_limit_address_attempts,
        account_attempts=settings.security.login_rate_limit_account_attempts,
    )
    auth = AuthService(clock, audit, session_factory, limiter)
    workflows = WorkflowService(clock, audit, activity_registry)
    notifications = NotificationService(clock, settings.notifications, secrets)
    tasks = TaskService(clock, audit, notifications, engine)
    schedules = ScheduleService(clock, audit)
    triggers = TriggerService(
        database=database,
        clock=clock,
        audit=audit,
        engine=engine,
        data_root=settings.data.root,
        file_watch_enabled=settings.scheduler.enabled,
    )
    workers = WorkerPool(
        bus=bus,
        secret_store=secrets,
        clock=clock,
        on_result=engine.on_result,
        count=settings.workers.count,
        extra_folder=settings.activities.extra_folder,
        ai_enabled=settings.ai.enabled,
        ai_endpoint=settings.ai.endpoint,
        poll_seconds=settings.workers.poll_seconds,
        blocked_env=(settings.secrets.vault_token_env,),
        child_env=child_environment(settings),
    )
    container = Container(
        settings=settings,
        clock=clock,
        database=database,
        secrets=secrets,
        audit=audit,
        bus=bus,
        registry=activity_registry,
        engine=engine,
        auth=auth,
        workflows=workflows,
        notifications=notifications,
        tasks=tasks,
        schedules=schedules,
        triggers=triggers,
        workers=workers,
        events=events,
        session_factory=session_factory,
    )
    if start:
        container.startup(start_background=True)
    return container


def workspace_for(settings: Settings, run_id: str) -> Path:
    return settings.data.workspaces / run_id
