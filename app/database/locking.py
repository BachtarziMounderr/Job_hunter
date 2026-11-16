"""Serialize scheduled runs without an additional queue or service."""

import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, text


@contextmanager
def execution_lock(engine: Engine):
    """Use a session-level PostgreSQL advisory lock or an OS-released SQLite file lock."""
    if engine.dialect.name == "postgresql":
        with engine.connect() as connection, connection.begin():
            # Transaction locks are safe with PgBouncer and released on disconnect.
            # Stay above the daily workflow's 45-minute limit while CPU inference is active.
            connection.execute(text("SET LOCAL idle_in_transaction_session_timeout = '60min'"))
            acquired = connection.scalar(text("SELECT pg_try_advisory_xact_lock(1095322184)"))
            if not acquired:
                raise RuntimeError("Another pipeline is already running")
            yield
        return
    path = Path(engine.url.database or "data/job_hunter.db").with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError("Another pipeline is already running") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
