import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from catalog_api.models import Transcription


@dataclass(frozen=True)
class Reading:
    """What is known about an Image's text, worked out from its Transcriptions.

    Current text is the latest Human transcription, otherwise the latest Machine one. An Image is
    verified when it has at least one Human transcription. Review status is a separate matter.
    """

    current_text: str | None = None
    text_source: str | None = None
    verified: bool = False


def readings_of(session: Session, image_ids: list[uuid.UUID]) -> dict[uuid.UUID, Reading]:
    """The Reading of each Image, from one query."""
    latest_human: dict[uuid.UUID, str] = {}
    latest_machine: dict[uuid.UUID, str] = {}
    # Only the newest row per Image and source: corrections are kept for good, and their text can be long.
    rows = session.scalars(
        select(Transcription)
        .where(Transcription.image_id.in_(image_ids))
        .distinct(Transcription.image_id, Transcription.source)
        .order_by(Transcription.image_id, Transcription.source, Transcription.created_at.desc())
    )
    for row in rows:
        (latest_human if row.source == "human" else latest_machine)[row.image_id] = row.text
    readings = {}
    for image_id in image_ids:
        if image_id in latest_human:
            readings[image_id] = Reading(latest_human[image_id], "human", True)
        elif image_id in latest_machine:
            readings[image_id] = Reading(latest_machine[image_id], "machine", False)
        else:
            readings[image_id] = Reading()
    return readings
