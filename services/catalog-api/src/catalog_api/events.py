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

    `builder_edit` is False when a Relation is what changed: the Ships on either end are announced
    by the Relation code already, so an organisation need not announce the Ships it built.
    """
    _changed(session, subject.kind, subject.id, op)
    for entity, entity_id in _dependents(session, subject, builder_edit):
        _changed(session, entity, entity_id, "upsert")


def _dependents(session: Session, subject: Subject, builder_edit: bool) -> list[tuple[str, uuid.UUID]]:
    """Documents linked to the Subject and, for a builder, the Ships it built and their Documents."""
    subject_ids = [subject.id]
    dependents: list[tuple[str, uuid.UUID]] = []
    if subject.kind == "organisation" and builder_edit:
        ships = session.scalars(
            select(Relation.from_subject_id).where(
                Relation.to_subject_id == subject.id,
                Relation.predicate == "built_by",
                Relation.deleted_at.is_(None),
            )
        ).all()
        dependents += [("ship", ship_id) for ship_id in ships]
        subject_ids += ships
    documents = session.scalars(
        select(DocumentSubject.document_id).where(DocumentSubject.subject_id.in_(subject_ids)).distinct()
    ).all()
    return dependents + [("document", document_id) for document_id in documents]


def document_changed(session: Session, document: Document) -> None:
    _changed(session, "document", document.id, "upsert")


def ocr_requested(session: Session, image_id: uuid.UUID) -> None:
    """Queue a job asking transcribe-worker to read this Image. Every job starts at attempt 1;
    only the worker counts further attempts."""
    _enqueue(session, "ocr.requested", {"image_id": str(image_id), "attempt": 1})
