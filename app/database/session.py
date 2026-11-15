"""Engine creation and explicit transactional session boundaries."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import Settings


def create_database_engine(settings: Settings) -> Engine:
    """Create an engine; construction alone does not verify connectivity."""
    url = make_url(settings.database_url.get_secret_value())
    if url.drivername == "sqlite" and url.database != ":memory:":
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, pool_pre_ping=True, hide_parameters=True)
    if url.drivername == "sqlite":

        @event.listens_for(engine, "connect")
        def set_sqlite_options(connection, connection_record) -> None:
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine


@contextmanager
def transaction(engine: Engine) -> Iterator[Session]:
    """Commit all source changes together, or roll them all back on failure."""
    with Session(engine) as session, session.begin():
        yield session
