from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session, session.begin():
        yield session
