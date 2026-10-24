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
from catalog_api.relations import announce_counterparts
from catalog_api.source_keys import LIMIT, SourceKeyIn, flush_or_conflict, lookup_filter, refuse_if_taken

router = APIRouter(prefix="/api/catalog")


class OrganisationFacts(BaseModel):
    organisation_type: str | None = None
    place: str | None = None


class OrganisationIn(OrganisationFacts, SourceKeyIn):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class OrganisationOut(OrganisationFacts):
    id: uuid.UUID
    name: str | None
    created_by: str
    source_system: str | None
    source_id: str | None


def organisation_out(
    session: Session, subject: Subject, organisation: Organisation
) -> OrganisationOut:
    return OrganisationOut(
        id=subject.id,
        name=current_name(session, subject.id),
        created_by=subject.created_by,
        source_system=subject.source_system,
        source_id=subject.source_id,
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
    refuse_if_taken(session, Subject, new.source_system, new.source_id, "A record")
    subject = Subject(kind="organisation", created_by=author, source_system=new.source_system, source_id=new.source_id)
    session.add(subject)
    flush_or_conflict(session, new.source_system, new.source_id, "A record")
    organisation = Organisation(
        subject_id=subject.id, organisation_type=new.organisation_type, place=new.place
    )
    session.add(organisation)
    session.add(SubjectName(subject_id=subject.id, name=new.name, created_by=author))
    session.flush()
    record_changed(session, subject)
    return organisation_out(session, subject, organisation)


@router.get("/organisations", dependencies=[Depends(staff_name)])
def find_organisations_by_source(
    key: tuple[str, str | None] = Depends(lookup_filter), session: Session = Depends(get_session)
) -> list[OrganisationOut]:
    """Organisations that came from one source: one by its full key, or all of a system's, oldest first."""
    system, ident = key
    query = (
        select(Subject, Organisation)
        .join(Organisation, Organisation.subject_id == Subject.id)
        .where(Subject.source_system == system, Subject.deleted_at.is_(None))
        .order_by(Subject.created_at)
        .limit(LIMIT)
    )
    if ident is not None:
        query = query.where(Subject.source_id == ident)
    return [organisation_out(session, subject, organisation) for subject, organisation in session.execute(query)]


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
    announce_counterparts(session, subject)
    soft_delete(subject)
    record_changed(session, subject, "delete")
