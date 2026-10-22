import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session

from catalog_api.auth import staff_name
from catalog_api.db import get_session
from catalog_api.models import Ship, Subject, SubjectName

router = APIRouter(prefix="/api/catalog")


class ShipIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ShipOut(BaseModel):
    id: uuid.UUID
    name: str
    created_by: str


def current_name(session: Session, subject_id: uuid.UUID) -> str:
    # A name with no end date is the one in use; the newest such name wins.
    return session.scalars(
        select(SubjectName.name)
        .where(
            SubjectName.subject_id == subject_id,
            SubjectName.deleted_at.is_(None),
            SubjectName.date_to.is_(None),
        )
        .order_by(SubjectName.created_at.desc())
        .limit(1)
    ).one()


@router.post("/ships", status_code=201)
def create_ship(
    ship: ShipIn,
    author: str = Depends(staff_name),
    session: Session = Depends(get_session),
) -> ShipOut:
    subject = Subject(kind="ship", created_by=author)
    session.add(subject)
    session.flush()
    session.add(Ship(subject_id=subject.id))
    session.add(SubjectName(subject_id=subject.id, name=ship.name, created_by=author))
    session.flush()
    return ShipOut(id=subject.id, name=ship.name, created_by=author)


@router.get("/ships/{ship_id}")
def read_ship(
    ship_id: uuid.UUID,
    author: str = Depends(staff_name),
    session: Session = Depends(get_session),
) -> ShipOut:
    subject = session.scalars(
        select(Subject).where(
            Subject.id == ship_id, Subject.kind == "ship", Subject.deleted_at.is_(None)
        )
    ).one_or_none()
    if subject is None:
        raise HTTPException(status_code=404, detail="Ship not found")
    return ShipOut(
        id=subject.id, name=current_name(session, subject.id), created_by=subject.created_by
    )
