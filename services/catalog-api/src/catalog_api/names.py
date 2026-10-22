import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session

from catalog_api.auth import staff_name
from catalog_api.dates import UncertainDate, present
from catalog_api.db import get_session, soft_delete
from catalog_api.events import record_changed
from catalog_api.models import Subject, SubjectName

router = APIRouter(prefix="/api/catalog")


class NameIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    name_type: Literal["given", "alias"] = "given"
    date: UncertainDate | None = None
    source: str | None = None


class NameOut(BaseModel):
    id: uuid.UUID
    name: str
    name_type: str
    date: UncertainDate | None
    source: str | None


def names_of(session: Session, subject_id: uuid.UUID) -> list[SubjectName]:
    """A Subject's Names, oldest first; undated Names come before dated ones."""
    names = session.scalars(
        select(SubjectName).where(
            SubjectName.subject_id == subject_id, SubjectName.deleted_at.is_(None)
        )
    ).all()
    return sorted(names, key=lambda n: (n.date_from or date.min, n.date_to or date.max, n.created_at))


def current_name(session: Session, subject_id: uuid.UUID) -> str | None:
    """The Name with no end date, or else the one that ended last."""
    names = names_of(session, subject_id)
    if not names:
        return None
    return max(names, key=lambda n: (n.date_to or date.max, n.date_from or date.min, n.created_at)).name


def find_subject(session: Session, subject_id: uuid.UUID) -> Subject:
    subject = session.scalars(
        select(Subject).where(Subject.id == subject_id, Subject.deleted_at.is_(None))
    ).one_or_none()
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    return subject


def name_out(name: SubjectName) -> NameOut:
    return NameOut(
        id=name.id,
        name=name.name,
        name_type=name.name_type,
        date=present(name.period),
        source=name.source,
    )


def end_current_name(session: Session, subject_id: uuid.UUID, new_start: date | None) -> None:
    """A new Name with no end replaces the open-ended one, which ends where the new one begins."""
    previous = [n for n in names_of(session, subject_id) if n.date_to is None]
    if not previous:
        return
    if new_start is None:
        raise HTTPException(
            status_code=422,
            detail="A rename needs the date it happened: set date.date_from on the new Name",
        )
    for old in previous:
        if old.date_from and new_start < old.date_from:
            raise HTTPException(
                status_code=422,
                detail=f"The new Name cannot start before {old.name} began ({old.date_from})",
            )
        old.period = UncertainDate(old.date_text, old.date_from, new_start)


@router.post("/subjects/{subject_id}/names", status_code=201)
def add_name(
    subject_id: uuid.UUID,
    new: NameIn,
    author: str = Depends(staff_name),
    session: Session = Depends(get_session),
) -> NameOut:
    subject = find_subject(session, subject_id)
    period = present(new.date)
    if period is None or period.date_to is None:
        end_current_name(session, subject_id, period.date_from if period else None)
    name = SubjectName(
        subject_id=subject_id,
        name=new.name,
        name_type=new.name_type,
        period=period,
        source=new.source,
        created_by=author,
    )
    session.add(name)
    session.flush()
    record_changed(session, subject)
    return name_out(name)


@router.get("/subjects/{subject_id}/names", dependencies=[Depends(staff_name)])
def read_names(subject_id: uuid.UUID, session: Session = Depends(get_session)) -> list[NameOut]:
    find_subject(session, subject_id)
    return [name_out(name) for name in names_of(session, subject_id)]


@router.delete("/names/{name_id}", status_code=204, dependencies=[Depends(staff_name)])
def delete_name(name_id: uuid.UUID, session: Session = Depends(get_session)) -> None:
    name = session.scalars(
        select(SubjectName).where(SubjectName.id == name_id, SubjectName.deleted_at.is_(None))
    ).one_or_none()
    if name is None:
        raise HTTPException(status_code=404, detail="Name not found")
    soft_delete(name)
    record_changed(session, find_subject(session, name.subject_id))
