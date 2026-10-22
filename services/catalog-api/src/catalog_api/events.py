from typing import Literal

from sqlalchemy.orm import Session

from catalog_api.models import Document, Outbox, Subject


def _enqueue(session: Session, entity: str, entity_id, op: Literal["upsert", "delete"]) -> None:
    session.add(
        Outbox(
            event_type="record.changed",
            payload={"entity": entity, "id": str(entity_id), "op": op},
        )
    )


def record_changed(
    session: Session, subject: Subject, op: Literal["upsert", "delete"] = "upsert"
) -> None:
    """Queue a record.changed event in the caller's transaction, for the relay to publish."""
    _enqueue(session, subject.kind, subject.id, op)


def document_changed(session: Session, document: Document) -> None:
    _enqueue(session, "document", document.id, "upsert")
