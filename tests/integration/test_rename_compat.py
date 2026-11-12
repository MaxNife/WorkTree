"""The rename from uaf to WorkTree (docs/03 phase 0 item 4) and its one-release compatibility.

Old ``UAF_*`` variables, the ``uaf`` command and the old cookies keep working, with a warning;
the new names win. The exit check, that ``uaf`` appears only in compatibility shims, is a test.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import compat
from app.adapters.db.schema import LegacyDatabaseFound, upgrade_database
from app.adapters.secrets.local import LocalSecretStore
from app.cli import db_upgrade
from app.config import Settings, load_settings
from app.domain.clock import FakeClock

REPO = Path(__file__).resolve().parents[2]
PASSWORD = "FixturePassword123!"

# Every tracked file allowed to mention the old name, each for a stated reason.
SHIMS = {
    "app/compat.py": "the old names, in one place",
    "web/src/compat.ts": "the web client's old cookie and storage names",
    "web/src/components/shell/layout.ts": "moves the old storage key once",
    "web/src/stores/preferences.ts": "moves the old storage key once",
    "app/config.py": "reads UAF_ settings below WORKTREE_",
    "app/adapters/secrets/local.py": "reads UAF_SECRET_ below WORKTREE_SECRET_",
    "app/adapters/secrets/base.py": "uaf_internal_ stays reserved",
    "app/security/sessions.py": "salt and stored audit-key name kept",
    "app/workers/process.py": "children drop both prefixes",
    "app/adapters/db/schema.py": "refuses to start beside the old database file",
    "activities/automation.py": "both prefixes reserved; old run variables passed to robots",
    "pyproject.toml": "the old command name",
    "tests/integration/test_rename_compat.py": "these tests",
    "tests/integration/test_security.py": "old names stay refused or stripped",
    "tests/integration/test_secrets.py": "the old secret prefix still resolves",
    "tests/integration/test_process_activities.py": "the old prefix stays reserved for robots",
    "tests/integration/test_web_bundle.py": "the old name is absent from the page",
    "tests/unit/test_settings_clock_logging.py": "clears both prefixes",
    "web/tests/stores.test.ts": "the old storage key moves",
    "web/tests/shell.test.ts": "the old CSRF cookie still works",
}


def test_uaf_appears_only_in_compatibility_shims() -> None:
    """docs/03 phase 0 exit check: ``grep -ri uaf`` finds only the compatibility shims."""
    listed = subprocess.run(
        ["git", "grep", "-l", "-i", "uaf", "--", ".", ":!web/dist", ":!uv.lock"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    assert sorted(set(listed) - set(SHIMS)) == []


def test_new_variables_win_and_old_ones_still_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WORKTREE_CONFIG", str(tmp_path / "absent.yaml"))
    monkeypatch.setenv("UAF_WORKERS__COUNT", "5")
    assert Settings().workers.count == 5
    monkeypatch.setenv("WORKTREE_WORKERS__COUNT", "3")
    assert Settings().workers.count == 3
    monkeypatch.delenv("WORKTREE_CONFIG")
    monkeypatch.setenv("UAF_CONFIG", "old.yaml")
    assert compat.env("CONFIG") == "old.yaml"
    monkeypatch.setenv("WORKTREE_CONFIG", "new.yaml")
    assert compat.env("CONFIG") == "new.yaml"


def test_using_an_old_variable_logs_a_deprecation_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    compat._warned.clear()
    monkeypatch.setenv("WORKTREE_CONFIG", str(tmp_path / "absent.yaml"))
    monkeypatch.setenv("UAF_WORKERS__COUNT", "2")
    with caplog.at_level("WARNING", logger="worktree.compat"):
        load_settings(data={"root": tmp_path, "playwright_state": tmp_path / "pw"})
    assert "UAF_WORKERS__COUNT is deprecated" in caplog.text
    assert "WORKTREE_WORKERS__COUNT" in caplog.text


def test_old_secret_variables_resolve_once_each(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LocalSecretStore(tmp_path / "s.json", FakeClock())
    monkeypatch.setenv("UAF_SECRET_OLD_KEY", "from-old")
    monkeypatch.setenv("UAF_SECRET_BOTH", "old-value")
    monkeypatch.setenv("WORKTREE_SECRET_BOTH", "new-value")
    assert store.get("old_key") == "from-old"
    assert store.get("both") == "new-value"
    assert sorted(info.name for info in store.list_metadata()) == ["both", "old_key"]


def test_an_old_session_cookie_still_signs_in_and_logout_clears_both(
    client: TestClient,
) -> None:
    login = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert login.status_code == 200
    assert "worktree_session" in login.headers.get("set-cookie", "")
    assert "uaf_session" not in login.headers.get("set-cookie", "")
    token = client.cookies.get("worktree_session")
    csrf = login.json()["csrf_token"]
    old = TestClient(client.app)
    old.cookies.set("uaf_session", token)
    assert old.get("/api/auth/me").status_code == 200
    with old.websocket_connect("/api/events") as socket:
        assert socket.receive_json()["type"] == "connected"
    out = old.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
    assert out.status_code == 200
    cleared = out.headers.get_list("set-cookie")
    for name in ("worktree_session", "worktree_csrf", "uaf_session", "uaf_csrf"):
        assert any(cookie.startswith(f"{name}=") for cookie in cleared), name


def test_the_new_default_database_is_not_created_beside_the_old_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "uaf.db").write_bytes(b"")
    url = f"sqlite:///{(tmp_path / 'worktree.db').as_posix()}"
    with pytest.raises(LegacyDatabaseFound, match="move"):
        upgrade_database(url)
    assert not (tmp_path / "worktree.db").exists()
    settings: Any = argparse.Namespace(database=argparse.Namespace(url=url))
    assert db_upgrade(argparse.Namespace(), settings) == 1
    assert "uaf.db" in capsys.readouterr().err
    # With the file moved, or the URL pointing at the old file, it proceeds.
    old_url = f"sqlite:///{(tmp_path / 'uaf.db').as_posix()}"
    upgrade_database(old_url)
