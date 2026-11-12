"""Command-line interface: serve, db, create-user, validate, run, list-activities, verify-audit."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import time
from pathlib import Path
from typing import Any

from app.adapters.db.schema import (
    UPGRADE_COMMAND,
    AdoptionRefused,
    SchemaNotCurrent,
    check_database,
    ensure_schema_current,
    head_revision,
    schema_status,
    upgrade_database,
)
from app.config import (
    InsecureConfiguration,
    Settings,
    assert_startup_safe,
    is_insecure_password,
    load_settings,
)
from app.container import build_container, seed_reference_data
from app.domain.enums import TERMINAL_RUN_STATUSES, Role, RunStatus
from app.domain.workflow import load_workflow_yaml, validate_definition
from app.errors import AppError
from app.services.secrets import list_secrets, set_policy


def _schema_ready(settings: Settings, *, prefix: str = "error") -> bool:
    """Refuse, with one line naming the fix, when the database is not at the head revision."""
    try:
        ensure_schema_current(settings.database.url)
    except SchemaNotCurrent as exc:
        print(f"{prefix}: {exc}", file=sys.stderr)
        return False
    return True


def _container(settings: Settings) -> Any:
    container = build_container(settings)
    seed_reference_data(container.database)
    return container


def create_user(args: argparse.Namespace, settings: Settings) -> int:
    password = args.password or os.environ.get("UAF_BOOTSTRAP_PASSWORD")
    if not password:
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm: ")
        if password != confirm:
            print("passwords do not match", file=sys.stderr)
            return 2
    if is_insecure_password(password):
        print("refusing a default or empty password", file=sys.stderr)
        return 2
    if not _schema_ready(settings):
        return 2
    container = _container(settings)
    try:
        with container.database.session() as session:
            user = container.auth.create_user(
                session,
                username=args.username,
                password=password,
                role=Role(args.role),
                display_name=args.display_name or args.username,
                actor="cli",
            )
            print(f"created user {user.username} with role {args.role}")
    except AppError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 1
    finally:
        container.shutdown()
    return 0


def list_activities(args: argparse.Namespace, settings: Settings) -> int:
    container = build_container(settings)
    try:
        for activity in container.registry.all():
            print(f"{activity.name:28} {activity.category:30} {activity.description}")
    finally:
        container.shutdown()
    return 0


def validate(args: argparse.Namespace, settings: Settings) -> int:
    path = Path(args.workflow)
    if not path.is_file():
        print(f"error: {path} does not exist", file=sys.stderr)
        return 2
    try:
        definition = load_workflow_yaml(path.read_text(encoding="utf-8"))
    except AppError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 2
    container = build_container(settings)
    try:
        issues = validate_definition(definition, container.registry.names())
    finally:
        container.shutdown()
    if issues:
        for issue in issues:
            print(f"{issue.code}: {issue}", file=sys.stderr)
        return 1
    print(f"{definition.name}: valid ({len(definition.steps)} steps)")
    return 0


def verify_audit(args: argparse.Namespace, settings: Settings) -> int:
    if not _schema_ready(settings):
        return 2
    container = build_container(settings)
    try:
        with container.database.session() as session:
            check = container.audit.verify(session)
        print(f"{check.message} ({check.rows} rows)")
        return 0 if check.ok else 1
    finally:
        container.shutdown()


def run_workflow(args: argparse.Namespace, settings: Settings) -> int:
    if not _schema_ready(settings):
        return 2
    container = _container(settings)
    container.workers.start()
    try:
        with container.database.session() as session:
            workflow_id = args.id or container.workflows.by_name(session, args.workflow).id
        run = container.engine.start_run(
            workflow_id=workflow_id,
            environment=args.environment,
            trigger="manual",
            requested_by="cli",
            inputs={},
        )
        print(f"run {run.id} started")
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            container.engine.tick()
            with container.database.session() as session:
                current = session.get(type(run), run.id)
                if current is None:
                    print("run disappeared", file=sys.stderr)
                    return 1
                status = current.status
            if status in {item.value for item in TERMINAL_RUN_STATUSES}:
                print(f"run {run.id} {status}")
                return 0 if status == RunStatus.DONE.value else 1
            time.sleep(0.2)
        print(f"run {run.id} did not finish within {args.timeout}s", file=sys.stderr)
        return 1
    except AppError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 1
    finally:
        container.shutdown()


def serve(args: argparse.Namespace, settings: Settings) -> int:
    import uvicorn

    from app.logging_setup import configure_logging
    from app.main import create_app

    try:
        assert_startup_safe(settings)
    except InsecureConfiguration as exc:
        print(f"refusing to start: {exc}", file=sys.stderr)
        return 2
    if not _schema_ready(settings, prefix="refusing to start"):
        return 2
    configure_logging(settings, console=True)
    container = _container(settings)
    if not container.has_admin():
        container.shutdown()
        print(
            "refusing to start: no active admin user. "
            "Run 'uaf create-user --username admin --role admin' first.",
            file=sys.stderr,
        )
        return 2
    application = create_app(settings, container=container, start_background=True)
    uvicorn.run(application, host=args.host, port=args.port, log_level=args.log_level)
    return 0


def secrets_list(args: argparse.Namespace, settings: Settings) -> int:
    """Names, sources and policies of the secrets workflows can use. Never values."""
    if not _schema_ready(settings):
        return 2
    container = _container(settings)
    try:
        with container.database.session() as session:
            rows = list_secrets(session, container.secrets)
    finally:
        container.shutdown()
    if not rows:
        print("no secrets")
        return 0
    for row in rows:
        flag = "  REFUSED: no environments" if row.refused_everywhere else ""
        hosts = ", ".join(row.allowed_hosts) or "-"
        envs = ", ".join(row.environments) or "-"
        print(f"{row.name}  [{row.source}]  environments: {envs}  hosts: {hosts}{flag}")
    return 0


def secrets_policy(args: argparse.Namespace, settings: Settings) -> int:
    """Replace a secret's policy (ADR 0001). Empty lists refuse every use."""
    if not _schema_ready(settings):
        return 2
    container = _container(settings)
    try:
        with container.database.session() as session:
            policy = set_policy(
                session,
                store=container.secrets,
                audit=container.audit,
                clock=container.clock,
                name=args.name,
                allowed_hosts=args.hosts,
                environments=args.env,
                actor="cli",
            )
    except AppError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 1
    finally:
        container.shutdown()
    print(
        f"{args.name}: environments {', '.join(policy['environments']) or 'none'}; "
        f"hosts {', '.join(policy['allowed_hosts']) or 'none'}"
    )
    return 0


def _unpoliced_notice(settings: Settings) -> None:
    """After an upgrade, name the secrets every use of which is now refused (ADR 0001)."""
    try:
        container = build_container(settings)
    except Exception:  # the secret store may need credentials this shell does not have
        return
    try:
        with container.database.session() as session:
            refused = [
                row.name
                for row in list_secrets(session, container.secrets)
                if row.refused_everywhere
            ]
    except Exception:
        return
    finally:
        container.shutdown()
    if refused and settings.secrets.enforce_policy:
        print(
            f"{len(refused)} secret(s) have no policy and every use will be refused: "
            + ", ".join(refused)
            + ". Set one with: uaf secrets policy NAME --env dev --hosts HOST ..."
        )


def db_upgrade(args: argparse.Namespace, settings: Settings) -> int:
    try:
        outcome = upgrade_database(settings.database.url)
    except AdoptionRefused as exc:
        print(f"error: {exc}", file=sys.stderr)
        for line in exc.differences:
            print(f"  - {line}", file=sys.stderr)
        return 1
    except SchemaNotCurrent as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for message in outcome.messages:
        print(message)
    _unpoliced_notice(settings)
    return 0


def db_current(args: argparse.Namespace, settings: Settings) -> int:
    status = schema_status(settings.database.url)
    print(f"current: {status.current or '(none)'}")
    print(f"head:    {head_revision()}")
    if status.up_to_date:
        print("the database is up to date")
    elif status.current is None and status.app_tables_present:
        print(f"no migration history, but tables exist; run '{UPGRADE_COMMAND}' to adopt them")
    else:
        print(f"the database is not up to date; run '{UPGRADE_COMMAND}'")
    return 0


def db_check(args: argparse.Namespace, settings: Settings) -> int:
    problems = check_database(settings.database.url)
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1
    print("the database is at head and matches the models")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="uaf", description="WorkTree")
    parser.add_argument("--config", default=os.environ.get("UAF_CONFIG", "config.yaml"))
    sub = parser.add_subparsers(dest="command", required=True)

    serve_parser = sub.add_parser("serve", help="start the control plane")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--log-level", default="info")
    serve_parser.set_defaults(func=serve)

    user_parser = sub.add_parser("create-user", help="create a local user")
    user_parser.add_argument("--username", required=True)
    user_parser.add_argument("--password", default="")
    user_parser.add_argument("--role", choices=[role.value for role in Role], default="viewer")
    user_parser.add_argument("--display-name", default="")
    user_parser.set_defaults(func=create_user)

    validate_parser = sub.add_parser("validate", help="validate a workflow YAML file")
    validate_parser.add_argument("workflow")
    validate_parser.set_defaults(func=validate)

    run_parser = sub.add_parser("run", help="run a workflow immediately")
    run_parser.add_argument("workflow", nargs="?", default="")
    run_parser.add_argument("--id", default="")
    run_parser.add_argument("--environment", default="dev", choices=["dev", "test", "prod"])
    run_parser.add_argument("--timeout", type=float, default=120)
    run_parser.set_defaults(func=run_workflow)

    list_parser = sub.add_parser("list-activities", help="list discovered activities")
    list_parser.set_defaults(func=list_activities)

    audit_parser = sub.add_parser("verify-audit", help="verify the audit hash chain")
    audit_parser.set_defaults(func=verify_audit)

    secrets_parser = sub.add_parser("secrets", help="list secrets and set their policies")
    secrets_sub = secrets_parser.add_subparsers(dest="secrets_command", required=True)
    secrets_sub.add_parser("list", help="names, sources and policies (never values)").set_defaults(
        func=secrets_list
    )
    policy_parser = secrets_sub.add_parser(
        "policy", help="replace a secret's allowed hosts and environments"
    )
    policy_parser.add_argument("name")
    policy_parser.add_argument("--hosts", nargs="*", default=[], help="hosts or *.domain")
    policy_parser.add_argument(
        "--env", nargs="*", default=[], choices=["dev", "test", "prod"], help="environments"
    )
    policy_parser.set_defaults(func=secrets_policy)

    db_parser = sub.add_parser("db", help="manage the database schema (Alembic migrations)")
    db_sub = db_parser.add_subparsers(dest="db_command", required=True)
    db_sub.add_parser("upgrade", help="upgrade the schema to head").set_defaults(func=db_upgrade)
    db_sub.add_parser("current", help="show the current and head revisions").set_defaults(
        func=db_current
    )
    db_sub.add_parser("check", help="fail unless the schema is at head with no drift").set_defaults(
        func=db_check
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    os.environ["UAF_CONFIG"] = args.config
    settings = load_settings()
    result: int = args.func(args, settings)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
