"""Database engine/session management and the declarative base.

SQLite locally (ADR-0003) via SQLAlchemy 2.0. A ``UTCDateTime`` type keeps all
stored datetimes timezone-aware UTC across the SQLite round-trip (NFR-02).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, Engine, TypeDecorator, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from orbitmind.core.timeutils import ensure_utc


class UTCDateTime(TypeDecorator[datetime]):
    """Store timezone-aware UTC datetimes and return them tz-aware (UTC)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return ensure_utc(value)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Database:
    """Own the engine and session factory for one database URL.

    Non-SQLite pools validate connections at checkout and replace connections that
    died while idle. Checkout validation cannot recover an in-flight transaction:
    failures are surfaced, never silently retried, and an uncertain commit is never
    replayed. Any safe retry belongs to an outer boundary that owns idempotency.
    """

    def __init__(self, url: str, *, recycle_seconds: int | None = None) -> None:
        self._url = url
        connect_args: dict[str, Any] = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
            self._ensure_sqlite_parent(url)
        engine_kwargs: dict[str, Any] = {"future": True, "connect_args": connect_args}
        if not url.startswith("sqlite"):
            engine_kwargs["pool_pre_ping"] = True
            if recycle_seconds is not None:
                engine_kwargs["pool_recycle"] = recycle_seconds
        self.engine: Engine = create_engine(url, **engine_kwargs)
        self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)

    @staticmethod
    def _ensure_sqlite_parent(url: str) -> None:
        # sqlite:///./data/orbitmind.db  ->  ./data/orbitmind.db
        prefix = "sqlite:///"
        if url.startswith(prefix):
            db_path = Path(url[len(prefix) :])
            if str(db_path) not in (":memory:", ""):
                db_path.parent.mkdir(parents=True, exist_ok=True)

    def create_all(self) -> None:
        """Create all tables from the ORM metadata (local/dev convenience)."""
        Base.metadata.create_all(self.engine)

    @property
    def dialect(self) -> str:
        """The SQLAlchemy dialect name (e.g. 'sqlite', 'postgresql')."""
        return self.engine.dialect.name

    @property
    def is_postgres(self) -> bool:
        return self.engine.dialect.name == "postgresql"

    def session(self) -> Session:
        """Open a new session."""
        return self._session_factory()

    def check_connection(self) -> bool:
        """Return True if a trivial query succeeds."""
        from sqlalchemy import text

        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:
            return False
        return True

    def dispose(self) -> None:
        """Release pooled database resources owned by this instance."""

        self.engine.dispose()
