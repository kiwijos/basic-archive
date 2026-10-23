import uuid
from typing import Literal

from sqlalchemy.orm import Session

from catalog_api.contracts import validate
from catalog_api.models import Document, Outbox, Subject


def _enqueue(session: Session, event_type: str, payload: dict) -> None:
    """Validate the payload against its contract, then queue it in the caller's transaction."""
    validate(event_type, payload)
    session.add(Outbox(event_type=event_type, payload=payload))


def _changed(
    session: Session, entity: str, entity_id: uuid.UUID, op: Literal["upsert", "delete"]
) -> None:
    _enqueue(session, "record.changed", {"entity": entity, "id": str(entity_id), "op": op})


def record_changed(
    session: Session, subject: Subject, op: Literal["upsert", "delete"] = "upsert"
) -> None:
    """Queue a record.changed event for the relay to publish."""
    _changed(session, subject.kind, subject.id, op)


def document_changed(session: Session, document: Document) -> None:
    _changed(session, "document", document.id, "upsert")


def ocr_requested(session: Session, image_id: uuid.UUID, attempt: int = 1) -> None:
    """Queue a job asking transcribe-worker to read this Image."""
    _enqueue(session, "ocr.requested", {"image_id": str(image_id), "attempt": attempt})
