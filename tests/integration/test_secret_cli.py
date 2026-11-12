"""``uaf secrets list|policy`` and the upgrade notice (ADR 0001)."""

from __future__ import annotations

import argparse

import pytest

from app.adapters.db.schema import upgrade_database
from app.cli import _unpoliced_notice, build_parser, secrets_list, secrets_policy, verify_audit
from app.config import Settings
from app.container import Container

PLANTED = "Cli-Planted-Value-4Kq9"


@pytest.fixture(autouse=True)
def migrated(container: Container, settings: Settings) -> None:
    """The commands refuse a database that is not at head; adopt the test database first."""
    upgrade_database(settings.database.url)


def _policy(settings: Settings, name: str, hosts: list[str], env: list[str]) -> int:
    return secrets_policy(argparse.Namespace(name=name, hosts=hosts, env=env), settings)


def test_the_command_sets_a_policy_and_the_audit_chain_still_verifies(
    container: Container, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    container.secrets.set("bank_key", PLANTED)
    assert (
        _policy(settings, "bank_key", ["API.bank.example.", "*.corp.example"], ["test", "dev"]) == 0
    )
    out = capsys.readouterr().out
    assert "environments dev, test" in out and "api.bank.example" in out
    assert secrets_list(argparse.Namespace(), settings) == 0
    listed = capsys.readouterr().out
    assert "bank_key" in listed and "api.bank.example, *.corp.example" in listed
    assert PLANTED not in listed and "session_signing_key" not in listed
    assert verify_audit(argparse.Namespace(), settings) == 0


def test_bad_hosts_internal_names_and_unknown_secrets_are_refused(
    container: Container, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    container.secrets.set("bank_key", PLANTED)
    assert _policy(settings, "bank_key", ["*"], ["dev"]) == 1
    assert _policy(settings, "session_signing_key", [], ["dev"]) == 1
    assert _policy(settings, "missing", [], ["dev"]) == 1
    assert "not valid" in capsys.readouterr().err


def test_the_parser_offers_the_commands() -> None:
    args = build_parser().parse_args(
        ["secrets", "policy", "k", "--hosts", "a.example.com", "--env", "dev", "prod"]
    )
    assert args.func is secrets_policy and args.env == ["dev", "prod"]
    assert build_parser().parse_args(["secrets", "list"]).func is secrets_list


def test_the_upgrade_names_the_secrets_that_will_be_refused(
    container: Container, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    settings.secrets.enforce_policy = True
    container.secrets.set("old_one", PLANTED)
    container.secrets.set("old_two", PLANTED)
    container.secrets.set("ready", PLANTED)
    _policy(settings, "ready", [], ["dev"])
    capsys.readouterr()
    _unpoliced_notice(settings)
    out = capsys.readouterr().out
    assert "2 secret(s) have no policy" in out
    assert "old_one, old_two" in out and "ready" not in out.split(":")[1]
    assert "uaf secrets policy" in out and PLANTED not in out
