import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from catalog_api.contracts import validate
from catalog_api.models import Document, DocumentSubject, Outbox, Relation, Subject


def _enqueue(session: Session, event_type: str, payload: dict) -> None:
    """Validate the payload against its contract, then queue it in the caller's transaction."""
    validate(event_type, payload)
    session.add(Outbox(event_type=event_type, payload=payload))


def _changed(
    session: Session, entity: str, entity_id: uuid.UUID, op: Literal["upsert", "delete"]
) -> None:
    _enqueue(session, "record.changed", {"entity": entity, "id": str(entity_id), "op": op})


def record_changed(
    session: Session,
    subject: Subject,
    op: Literal["upsert", "delete"] = "upsert",
    *,
    builder_edit: bool = True,
) -> None:
    """Queue a record.changed event for the relay to publish, and one for everything whose
    indexed record shows this Subject's facts.

    `builder_edit` is False when a Relation is what changed: the Subjects on either end are announced
    by the Relation code already, so they need not announce each other again.
    """
    _changed(session, subject.kind, subject.id, op)
    for entity, entity_id in _dependents(session, subject, builder_edit and op == "upsert"):
        _changed(session, entity, entity_id, "upsert")


def _dependents(session: Session, subject: Subject, own_edit: bool) -> list[tuple[str, uuid.UUID]]:
    """What shows this Subject: the Documents linked to it, and when the Subject itself changed, the
    Subjects it is related to (their pages name it) and, for a builder, its Ships' Documents."""
    dependents: list[tuple[str, uuid.UUID]] = []
    document_subjects = [subject.id]
    if own_edit:
        counterparts = session.execute(
            select(Subject.kind, Subject.id)
            .join(Relation, ((Relation.from_subject_id == Subject.id) & (Relation.to_subject_id == subject.id))
                  | ((Relation.to_subject_id == Subject.id) & (Relation.from_subject_id == subject.id)))
            .where(Relation.deleted_at.is_(None))
            .distinct()
        ).all()
        dependents += [(kind, subject_id) for kind, subject_id in counterparts]
        if subject.kind == "organisation":
            document_subjects += [i for kind, i in counterparts if kind == "ship"]
    documents = session.scalars(
        select(DocumentSubject.document_id).where(DocumentSubject.subject_id.in_(document_subjects)).distinct()
    ).all()
    return dependents + [("document", document_id) for document_id in documents]


def document_changed(session: Session, document: Document) -> None:
    """A Document's record changed, and so did the pages of the Subjects it is linked to: they list it
    with its title and whether it is verified."""
    _changed(session, "document", document.id, "upsert")
    linked = session.execute(
        select(Subject.kind, Subject.id)
        .join(DocumentSubject, DocumentSubject.subject_id == Subject.id)
        .where(DocumentSubject.document_id == document.id)
    ).all()
    for kind, subject_id in linked:
        _changed(session, kind, subject_id, "upsert")


def ocr_requested(session: Session, image_id: uuid.UUID) -> None:
    """Queue a job asking transcribe-worker to read this Image. Every job starts at attempt 1;
    only the worker counts further attempts."""
    _enqueue(session, "ocr.requested", {"image_id": str(image_id), "attempt": 1})
