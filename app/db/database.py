"""Database engine and session factory.

The application keeps no module-level global engine: a :class:`Database`
instance is created once in ``create_app`` and stored on ``app.state``, which
makes it trivial to point tests at a temporary SQLite file.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base

logger = logging.getLogger(__name__)


class Database:
    """Owns the SQLAlchemy engine and the session factory for the process."""

    def __init__(self, database_url: str) -> None:
        connect_args: Dict[str, Any] = {}
        if database_url.startswith("sqlite"):
            # Background tasks run in a worker thread, so the connection may not
            # be used by the thread that created it. SQLite allows this as long
            # as we opt out of the thread check.
            connect_args["check_same_thread"] = False

        self.database_url = database_url
        self.engine: Engine = create_engine(
            database_url, connect_args=connect_args, future=True
        )
        self.session_factory: sessionmaker[Session] = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
            future=True,
        )

    def create_all(self) -> None:
        """Create any missing tables (no migrations needed for this project)."""
        Base.metadata.create_all(self.engine)
        logger.info("Database ready at %s", self.database_url)

    def dispose(self) -> None:
        """Release pooled connections (used when the application shuts down)."""
        self.engine.dispose()
