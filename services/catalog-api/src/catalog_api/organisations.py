import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session

from catalog_api.auth import staff_name
from catalog_api.db import get_session, soft_delete
from catalog_api.events import record_changed
from catalog_api.models import Organisation, Subject, SubjectName
from catalog_api.names import current_name

router = APIRouter(prefix="/api/catalog")


class OrganisationFacts(BaseModel):
    organisation_type: str | None = None
    place: str | None = None


class OrganisationIn(OrganisationFacts):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class OrganisationOut(OrganisationFacts):
    id: uuid.UUID
    name: str | None
    created_by: str


def organisation_out(
    session: Session, subject: Subject, organisation: Organisation
) -> OrganisationOut:
    return OrganisationOut(
        id=subject.id,
        name=current_name(session, subject.id),
        created_by=subject.created_by,
        organisation_type=organisation.organisation_type,
        place=organisation.place,
    )


def find_organisation(session: Session, organisation_id: uuid.UUID) -> tuple[Subject, Organisation]:
    row = session.execute(
        select(Subject, Organisation)
        .join(Organisation, Organisation.subject_id == Subject.id)
        .where(Subject.id == organisation_id, Subject.deleted_at.is_(None))
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Organisation not found")
    return row


@router.post("/organisations", status_code=201)
def create_organisation(
    new: OrganisationIn,
    author: str = Depends(staff_name),
    session: Session = Depends(get_session),
) -> OrganisationOut:
    subject = Subject(kind="organisation", created_by=author)
    session.add(subject)
    session.flush()
    organisation = Organisation(
        subject_id=subject.id, organisation_type=new.organisation_type, place=new.place
    )
    session.add(organisation)
    session.add(SubjectName(subject_id=subject.id, name=new.name, created_by=author))
    session.flush()
    record_changed(session, subject)
    return organisation_out(session, subject, organisation)


@router.get("/organisations/{organisation_id}", dependencies=[Depends(staff_name)])
def read_organisation(
    organisation_id: uuid.UUID, session: Session = Depends(get_session)
) -> OrganisationOut:
    return organisation_out(session, *find_organisation(session, organisation_id))


@router.put("/organisations/{organisation_id}", dependencies=[Depends(staff_name)])
def update_organisation(
    organisation_id: uuid.UUID,
    facts: OrganisationFacts,
    session: Session = Depends(get_session),
) -> OrganisationOut:
    subject, organisation = find_organisation(session, organisation_id)
    organisation.organisation_type = facts.organisation_type
    organisation.place = facts.place
    session.flush()
    record_changed(session, subject)
    return organisation_out(session, subject, organisation)


@router.delete(
    "/organisations/{organisation_id}", status_code=204, dependencies=[Depends(staff_name)]
)
def delete_organisation(
    organisation_id: uuid.UUID, session: Session = Depends(get_session)
) -> None:
    subject, _ = find_organisation(session, organisation_id)
    soft_delete(subject)
    record_changed(session, subject, "delete")
