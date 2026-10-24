"""Where a record came from: a source system and the record's identifier there.

Both parts together make a key that is unique across Documents, and across Subjects (Ships and Organisations
share one namespace), so loading the same thing twice cannot make two records. The key is set when a record
is created and never changed, because other systems rely on it.
"""

import re
from typing import Annotated

from fastapi import HTTPException, Query
from pydantic import BaseModel, StringConstraints, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

PLAIN = r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$"
Plain = Annotated[str, StringConstraints(pattern=PLAIN)]
LIMIT = 200  # most records one lookup returns


class SourceKeyIn(BaseModel):
    """The optional key in a request body: both parts or neither."""

    source_system: Plain | None = None
    source_id: Plain | None = None

    @model_validator(mode="after")
    def both_or_neither(self) -> "SourceKeyIn":
        if (self.source_system is None) != (self.source_id is None):
            raise ValueError("source_system and source_id go together")
        return self


def key_from_form(source_system: str | None, source_id: str | None) -> tuple[str | None, str | None]:
    """The same rules for an upload, whose fields arrive as form text (empty text is the same as absent)."""
    system, ident = (source_system or None), (source_id or None)
    if (system is None) != (ident is None):
        raise HTTPException(status_code=422, detail="source_system and source_id go together")
    for value in (system, ident):
        if value is not None and not re.fullmatch(PLAIN, value):
            raise HTTPException(
                status_code=422,
                detail="A source key is plain text: letters, digits and . _ : / - , at most 100 characters",
            )
    return system, ident


def lookup_filter(
    source_system: Annotated[str, Query(pattern=PLAIN)],
    source_id: Annotated[str | None, Query(pattern=PLAIN)] = None,
) -> tuple[str, str | None]:
    """What a lookup asks for: one record by its full key, or everything from one system. Never everything."""
    return source_system, source_id


def refuse_if_taken(session: Session, model, system: str | None, ident: str | None, what: str) -> None:
    """409 when the key is already used, including by a record that was deleted (its row is still there)."""
    if system is None:
        return
    taken = session.execute(
        select(model.deleted_at).where(model.source_system == system, model.source_id == ident)
    ).first()
    if taken is not None:
        detail = f"{what} with source {system}/{ident} already exists"
        if taken.deleted_at is not None:
            detail += " (it was deleted, and its key stays reserved)"
        raise HTTPException(status_code=409, detail=detail)


def flush_or_conflict(session: Session, system: str | None, ident: str | None, what: str) -> None:
    """Flush, turning a clash with a record created a moment ago by someone else into the same 409."""
    try:
        session.flush()
    except IntegrityError as error:
        if system is not None and "source_key" in str(error.orig):
            raise HTTPException(status_code=409, detail=f"{what} with source {system}/{ident} already exists") from error
        raise
