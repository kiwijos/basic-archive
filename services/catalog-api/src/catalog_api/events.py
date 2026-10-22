from typing import Literal

from sqlalchemy.orm import Session

from catalog_api.models import Outbox, Subject


def record_changed(
    session: Session, subject: Subject, op: Literal["upsert", "delete"] = "upsert"
) -> None:
    """Queue a record.changed event in the caller's transaction, for the relay to publish."""
    session.add(
        Outbox(
            event_type="record.changed",
            payload={"entity": subject.kind, "id": str(subject.id), "op": op},
        )
    )
