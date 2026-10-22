"""Database engine and session management.

SQLite is the default. Oracle is supported through SQLAlchemy + python-oracledb thin mode;
dialect differences (sequences, JSON, booleans, `RETURNING`) are confined to this package.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.adapters.db.models import Base


def _sqlite_path(url: str) -> Path | None:
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return None
    raw = url[len(prefix) :]
    if raw.startswith(":memory:"):
        return None
    return Path(raw)


def build_engine(url: str, *, echo: bool = False) -> Engine:
    kwargs: dict[str, object] = {"echo": echo, "future": True}
    path = _sqlite_path(url)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    if url.endswith(":memory:") or url == "sqlite://":
        kwargs["poolclass"] = StaticPool
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)

    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection: object, _record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            if path is not None:
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


class Database:
    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.url = url
        self.engine = build_engine(url, echo=echo)
        self.session_factory = sessionmaker(
            bind=self.engine, expire_on_commit=False, autoflush=False, future=True
        )

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    def drop_all(self) -> None:
        Base.metadata.drop_all(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()
