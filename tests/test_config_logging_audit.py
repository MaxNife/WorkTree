"""Configuration, logging, masking and audit chain tests."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.audit.guard import AuditMutationError
from app.config import Settings, is_insecure_password, load_settings
from app.domain.masking import SecretMasker, get_masker
from app.logging_setup import (
    bind_correlation_id,
    clear_correlation_id,
    configure_logging,
    get_logger,
)
from app.security.masking import get_masker as compatibility_masker


def test_yaml_then_env_then_init_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        "app:\n  environment: test\ndatabase:\n  url: sqlite:///./yaml.db\nworkers:\n  count: 3\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("WORKTREE_CONFIG", str(config))
    monkeypatch.setenv("WORKTREE_DATABASE__URL", "sqlite:///./env.db")
    settings = load_settings()
    assert settings.database.url.endswith("env.db")
    assert settings.workers.count == 3
    assert settings.app.environment == "test"
    overridden = load_settings(database={"url": "sqlite:///./init.db"})
    assert overridden.database.url.endswith("init.db")


def test_invalid_values_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(workers={"count": 0})
    with pytest.raises(ValidationError):
        Settings(logging={"level": "LOUD"})
    with pytest.raises(ValidationError):
        Settings(secrets={"adapter": "vault", "vault_url": ""})


def test_insecure_password_detection() -> None:
    assert is_insecure_password("")
    assert is_insecure_password(" admin ")
    assert not is_insecure_password("LongPassword123!")


def test_secret_masker_handles_nested_values_and_requires_length() -> None:
    masker = SecretMasker()
    masker.register("super-secret")
    masker.register("")
    assert masker.known_count == 1
    masked = masker.mask_obj({"a": "x super-secret y", "b": ["super-secret"]})
    assert masked == {"a": "x *** y", "b": ["***"]}
    masker.clear()
    assert masker.known_count == 0
    assert compatibility_masker() is get_masker()


def test_logs_are_masked_and_carry_correlation_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(logging={"directory": tmp_path / "logs", "json_logs": True})
    get_masker().clear()
    get_masker().register("planted-secret-value")
    configure_logging(settings, console=False)
    bind_correlation_id("corr-123")
    try:
        get_logger("test").info("planted_secret", value="planted-secret-value")
    finally:
        clear_correlation_id()
    for handler in logging.getLogger().handlers:
        handler.flush()
    content = (tmp_path / "logs" / "worktree.log").read_text(encoding="utf-8")
    assert "planted-secret-value" not in content
    assert "***" in content
    parsed = json.loads(content.strip().splitlines()[-1])
    assert parsed["correlation_id"] == "corr-123"
    get_masker().clear()
    monkeypatch.setattr("app.logging_setup._configured", False)


def test_audit_chain_detects_tampering(container) -> None:
    with container.database.session() as session:
        container.audit.write(session, actor="one", action="first", after={"x": 1})
        container.audit.write(session, actor="two", action="second", after={"x": 2})
    with container.database.session() as session:
        assert container.audit.verify(session).ok
    with container.database.session() as session:
        from sqlalchemy import text

        session.execute(text("UPDATE audit_log SET actor = 'tamper' WHERE id = 1"))
    with container.database.session() as session:
        result = container.audit.verify(session)
        assert not result.ok
        assert result.first_bad_id == 1


def test_audit_orm_update_and_delete_are_rejected(container) -> None:
    with container.database.session() as session:
        before = container.audit.count(session)
        container.audit.write(session, actor="one", action="first")
    with pytest.raises(AuditMutationError), container.database.session() as session:
        from sqlalchemy import delete

        from app.adapters.db.models import AuditLog

        session.execute(delete(AuditLog))
    with container.database.session() as session:
        assert container.audit.count(session) == before + 1
