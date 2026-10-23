import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from catalog_api.auth import staff_name
from catalog_api.dates import UncertainDate, present
from catalog_api.db import get_session, soft_delete
from catalog_api.events import record_changed
from catalog_api.models import Relation, Subject
from catalog_api.names import current_name, find_subject

router = APIRouter(prefix="/api/catalog")

Predicate = Literal["built_by", "owned_by", "operated_by", "rebuilt_from"]

# The kind of Subject each end of a Relation must be.
ENDS: dict[str, tuple[str, str]] = {
    "built_by": ("ship", "organisation"),
    "owned_by": ("ship", "organisation"),
    "operated_by": ("ship", "organisation"),
    "rebuilt_from": ("ship", "ship"),
}


class RelationFacts(BaseModel):
    place: str | None = None
    date: UncertainDate | None = None
    source: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class RelationIn(RelationFacts):
    from_subject_id: uuid.UUID
    predicate: Predicate
    to_subject_id: uuid.UUID


class RelationOut(RelationFacts):
    id: uuid.UUID
    from_subject_id: uuid.UUID
    from_name: str | None
    predicate: str
    to_subject_id: uuid.UUID
    to_name: str | None


def relation_out(session: Session, relation: Relation) -> RelationOut:
    return RelationOut(
        id=relation.id,
        from_subject_id=relation.from_subject_id,
        from_name=current_name(session, relation.from_subject_id),
        predicate=relation.predicate,
        to_subject_id=relation.to_subject_id,
        to_name=current_name(session, relation.to_subject_id),
        place=relation.place,
        date=present(relation.period),
        source=relation.source,
        confidence=relation.confidence,
    )


def live_relations(session: Session, subject_id: uuid.UUID | None = None) -> Select:
    """Relations that are not deleted and whose two ends are not deleted, optionally of one Subject."""
    live_subjects = select(Subject.id).where(Subject.deleted_at.is_(None))
    query = select(Relation).where(
        Relation.from_subject_id.in_(live_subjects),
        Relation.to_subject_id.in_(live_subjects),
        Relation.deleted_at.is_(None),
    )
    if subject_id is not None:
        query = query.where(
            or_(Relation.from_subject_id == subject_id, Relation.to_subject_id == subject_id)
        )
    return query


def find_relation(session: Session, relation_id: uuid.UUID) -> Relation:
    relation = session.scalars(
        live_relations(session).where(Relation.id == relation_id)
    ).one_or_none()
    if relation is None:
        raise HTTPException(status_code=404, detail="Relation not found")
    return relation


def check_ends(session: Session, new: RelationIn) -> None:
    if new.from_subject_id == new.to_subject_id:
        raise HTTPException(status_code=422, detail="A Subject cannot be related to itself")
    subjects = {
        subject.id: subject
        for subject in session.scalars(
            select(Subject).where(
                Subject.id.in_([new.from_subject_id, new.to_subject_id]),
                Subject.deleted_at.is_(None),
            )
        )
    }
    if len(subjects) != 2:
        raise HTTPException(status_code=422, detail="Both ends of a Relation must be existing Subjects")
    from_kind, to_kind = ENDS[new.predicate]
    if (subjects[new.from_subject_id].kind, subjects[new.to_subject_id].kind) != (from_kind, to_kind):
        raise HTTPException(
            status_code=422,
            detail=f"{new.predicate} goes from a {from_kind} to a {to_kind}",
        )


def apply_facts(relation: Relation, facts: RelationFacts) -> None:
    relation.place = facts.place
    relation.period = facts.date
    relation.source = facts.source
    relation.confidence = facts.confidence


def announce(session: Session, relation: Relation) -> None:
    """A Relation is part of both Subjects' records, so any change to it changes both."""
    for subject_id in (relation.from_subject_id, relation.to_subject_id):
        record_changed(session, session.get(Subject, subject_id), builder_edit=False)


def announce_counterparts(session: Session, subject: Subject) -> None:
    """Call before deleting a Subject: its Relations vanish from the records of the Subjects it was related to."""
    for relation in session.scalars(live_relations(session, subject.id)):
        other_id = relation.to_subject_id if relation.from_subject_id == subject.id else relation.from_subject_id
        record_changed(session, session.get(Subject, other_id), builder_edit=False)


@router.post("/relations", status_code=201)
def create_relation(
    new: RelationIn,
    author: str = Depends(staff_name),
    session: Session = Depends(get_session),
) -> RelationOut:
    check_ends(session, new)
    relation = Relation(
        from_subject_id=new.from_subject_id,
        predicate=new.predicate,
        to_subject_id=new.to_subject_id,
        created_by=author,
    )
    apply_facts(relation, new)
    session.add(relation)
    session.flush()
    announce(session, relation)
    return relation_out(session, relation)


@router.put("/relations/{relation_id}", dependencies=[Depends(staff_name)])
def update_relation(
    relation_id: uuid.UUID, facts: RelationFacts, session: Session = Depends(get_session)
) -> RelationOut:
    relation = find_relation(session, relation_id)
    apply_facts(relation, facts)
    session.flush()
    announce(session, relation)
    return relation_out(session, relation)


@router.get("/subjects/{subject_id}/relations", dependencies=[Depends(staff_name)])
def read_relations(
    subject_id: uuid.UUID,
    predicate: Predicate | None = None,
    session: Session = Depends(get_session),
) -> list[RelationOut]:
    find_subject(session, subject_id)
    query = live_relations(session, subject_id)
    if predicate:
        query = query.where(Relation.predicate == predicate)
    relations = sorted(
        session.scalars(query), key=lambda r: (r.date_from or date.min, r.created_at)
    )
    return [relation_out(session, relation) for relation in relations]


@router.delete("/relations/{relation_id}", status_code=204, dependencies=[Depends(staff_name)])
def delete_relation(relation_id: uuid.UUID, session: Session = Depends(get_session)) -> None:
    relation = find_relation(session, relation_id)
    soft_delete(relation)
    announce(session, relation)
