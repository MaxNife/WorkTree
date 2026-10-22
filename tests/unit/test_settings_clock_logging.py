"""CP-02/CP-03: defaults, overrides, clock, DI wiring, correlation ids and telemetry hooks."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from app.config import Settings
from app.domain.clock import FakeClock, SystemClock
from app.domain.masking import get_masker
from app.logging_setup import configure_logging, correlation_scope, get_logger
from app.telemetry import configure_telemetry, is_enabled, span

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def no_config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UAF_CONFIG", str(tmp_path / "absent.yaml"))
    for key in list(__import__("os").environ):
        if key.startswith("UAF_") and key != "UAF_CONFIG":
            monkeypatch.delenv(key)


def test_defaults_are_safe_without_any_config(no_config_file: None) -> None:
    settings = Settings()
    assert settings.audit.retention_years == 7
    assert settings.ai.enabled is False
    assert settings.otel.enabled is False
    assert settings.bus.adapter == "db"
    assert settings.secrets.adapter == "local"
    assert settings.database.url.startswith("sqlite:///")
    assert settings.workers.count >= 1
    workspaces = settings.data.workspaces.resolve()
    state = settings.data.playwright_state.resolve()
    assert workspaces not in state.parents and state != workspaces, (
        "Playwright session state must live outside run workspaces"
    )


def test_repository_config_matches_defaults_and_holds_no_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = yaml.safe_load((REPO / "config.yaml").read_text(encoding="utf-8"))

    def keys(node: object) -> list[str]:
        if isinstance(node, dict):
            return [str(k) for k in node] + [k for v in node.values() for k in keys(v)]
        return []

    forbidden = {"vault_token", "password", "api_key", "client_secret", "token", "secret"}
    assert not forbidden & {key.lower() for key in keys(raw)}, "config.yaml must hold no secrets"
    monkeypatch.setenv("UAF_CONFIG", str(REPO / "config.yaml"))
    settings = Settings()
    assert settings.ai.enabled is False and settings.otel.enabled is False
    assert settings.audit.retention_years == 7


def test_override_file_and_env_layering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    override = tmp_path / "site.yaml"
    override.write_text("workers:\n  count: 5\nai:\n  enabled: true\n", encoding="utf-8")
    monkeypatch.setenv("UAF_CONFIG", str(override))
    monkeypatch.setenv("UAF_WORKERS__COUNT", "7")
    settings = Settings()
    assert settings.ai.enabled is True, "file overrides defaults"
    assert settings.workers.count == 7, "environment overrides the file"


@pytest.mark.parametrize(
    "bad",
    [
        {"workers": {"count": 0}},
        {"workers": {"count": 999}},
        {"bus": {"adapter": "kafka"}},
        {"secrets": {"adapter": "plaintext"}},
        {"security": {"session_ttl_minutes": 0}},
        {"app": {"environment": "staging"}},
    ],
)
def test_invalid_values_are_rejected(bad: dict[str, object]) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(**bad)  # type: ignore[arg-type]


def test_fake_and_system_clocks() -> None:
    start = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    clock = FakeClock(start)
    assert clock.now() == start
    clock.advance(minutes=5)
    clock.sleep(30)
    assert clock.now() == datetime(2026, 3, 1, 12, 5, 30, tzinfo=UTC)
    clock.set(start)
    assert clock.now() == start
    now = SystemClock().now()
    assert now.tzinfo is not None and now.utcoffset() == UTC.utcoffset(now)


def test_container_wires_shared_dependencies(container) -> None:
    assert container.engine.database is container.database
    assert container.bus.database is container.database
    assert container.engine.bus is container.bus
    assert container.engine.clock is container.clock is container.audit.clock


@pytest.fixture
def log_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    settings = Settings(logging={"directory": tmp_path / "logs", "json_logs": True})
    configure_logging(settings, console=False)
    yield tmp_path / "logs" / "uaf.log"
    monkeypatch.setattr("app.logging_setup._configured", False)
    get_masker().clear()


def _lines(path: Path) -> list[dict[str, object]]:
    for handler in logging.getLogger().handlers:
        handler.flush()
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_every_log_line_carries_a_correlation_id(log_file: Path) -> None:
    get_logger("t").info("outside_any_scope")
    logging.getLogger("third.party").warning("stdlib logger line")
    with correlation_scope("corr-run-1", run_id="run-1", step_id="step-a"):
        get_logger("t").info("inside_scope")
        logging.getLogger("third.party").warning("stdlib inside scope")
    lines = _lines(log_file)
    assert len(lines) >= 4
    assert all(line.get("correlation_id") for line in lines)
    scoped = [line for line in lines if line.get("correlation_id") == "corr-run-1"]
    assert len(scoped) == 2
    assert all(line["run_id"] == "run-1" and line["step_id"] == "step-a" for line in scoped)


def test_worker_log_lines_carry_the_runs_correlation_id(container, log_file: Path) -> None:
    from app.domain.workflow import WorkflowDefinition

    with container.database.session() as session:
        workflow, _ = container.workflows.save(
            session,
            WorkflowDefinition.model_validate(
                {"name": "log", "steps": [{"id": "s", "activity": "echo"}]}
            ),
            actor="admin",
            actor_roles=[__import__("app.domain.enums", fromlist=["Role"]).Role.ADMIN],
        )
    run = container.engine.start_run(workflow_id=workflow.id)
    assert run.correlation_id, "runs without a caller-supplied id get a generated one"
    assert container.workers.process_one()
    finished = [line for line in _lines(log_file) if line.get("event") == "activity_finished"]
    assert finished and finished[-1]["correlation_id"] == run.correlation_id
    assert finished[-1]["run_id"] == run.id


def test_telemetry_is_off_by_default_and_span_is_a_no_op() -> None:
    assert configure_telemetry(Settings()) is False
    assert not is_enabled()
    with span("uaf.test", attempt=1):
        pass


def test_enabling_telemetry_without_the_extra_degrades_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    real_import = builtins.__import__

    def no_otel(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("opentelemetry"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", no_otel)
    assert configure_telemetry(Settings(otel={"enabled": True})) is False
    assert not is_enabled()
