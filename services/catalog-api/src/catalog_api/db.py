from collections.abc import Iterator
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy.orm import Session


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session, session.begin():
        yield session


def soft_delete(record) -> None:
    """Hide a record from every read while keeping its row."""
    record.deleted_at = datetime.now(UTC)
