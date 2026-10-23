import logging
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from catalog_api.auth import staff_name
from catalog_api.db import get_session
from catalog_api.documents import find_image
from catalog_api.events import document_changed, ocr_requested
from catalog_api.models import Document, Image, Transcription

router = APIRouter(prefix="/api/catalog")
logger = logging.getLogger(__name__)

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class MachineResultIn(BaseModel):
    source: Literal["machine"]
    # A blank page legitimately reads as no text at all.
    text: str
    engine: NonBlank
    engine_version: NonBlank
    language: NonBlank
    confidence: float | None = Field(default=None, ge=0, le=1)


class FailureIn(BaseModel):
    reason: str = ""


class TranscriptionOut(BaseModel):
    id: uuid.UUID
    image_id: uuid.UUID
    source: str
    text: str
    engine: str | None
    engine_version: str | None
    language: str | None
    confidence: float | None
    created_by: str | None
    created_at: datetime


def move_image(session: Session, image_id: uuid.UUID, allowed_from: tuple[str, ...], to: str) -> bool:
    """Change an Image's Review status only if it is in one of the allowed states.

    One conditional UPDATE decides, so when two workers race for the same Image only one wins.
    """
    result = session.execute(
        update(Image)
        .where(Image.id == image_id, Image.review_status.in_(allowed_from))
        .values(review_status=to)
    )
    return result.rowcount == 1


def refuse_unless(moved: bool, image: Image, wanted: str) -> None:
    if not moved:
        raise HTTPException(
            status_code=409,
            detail=f"This Image is {image.review_status}, so it cannot be changed this way ({wanted})",
        )


def announce_document_of(session: Session, image: Image) -> None:
    document = session.get(Document, image.document_id)
    document_changed(session, document)


@router.post("/images/{image_id}/transcriptions", status_code=201)
def add_machine_transcription(
    image_id: uuid.UUID,
    result: MachineResultIn,
    author: str = Depends(staff_name),
    session: Session = Depends(get_session),
) -> TranscriptionOut:
    image = find_image(session, image_id)
    refuse_unless(move_image(session, image_id, ("pending",), "ocr_done"), image, "only a pending Image takes a result")
    transcription = Transcription(
        image_id=image_id,
        source="machine",
        text=result.text,
        engine=result.engine,
        engine_version=result.engine_version,
        language=result.language,
        confidence=result.confidence,
        created_by=author,
    )
    session.add(transcription)
    session.flush()
    session.refresh(transcription)
    announce_document_of(session, image)
    return transcription_out(transcription)


@router.get("/images/{image_id}/transcriptions", dependencies=[Depends(staff_name)])
def read_transcriptions(
    image_id: uuid.UUID, session: Session = Depends(get_session)
) -> list[TranscriptionOut]:
    find_image(session, image_id)
    rows = session.scalars(
        select(Transcription)
        .where(Transcription.image_id == image_id)
        .order_by(Transcription.created_at.desc())
    )
    return [transcription_out(row) for row in rows]


@router.post("/images/{image_id}/ocr-failure", dependencies=[Depends(staff_name)])
def report_ocr_failure(
    image_id: uuid.UUID, failure: FailureIn, session: Session = Depends(get_session)
) -> dict:
    image = find_image(session, image_id)
    refuse_unless(move_image(session, image_id, ("pending",), "failed"), image, "only a pending Image can fail")
    logger.warning("OCR failed for image %s: %s", image_id, failure.reason)
    announce_document_of(session, image)
    return {"review_status": "failed"}


@router.post("/images/{image_id}/ocr", status_code=202, dependencies=[Depends(staff_name)])
def read_image_again(image_id: uuid.UUID, session: Session = Depends(get_session)) -> dict:
    image = find_image(session, image_id)
    moved = move_image(session, image_id, ("failed", "ocr_done"), "pending")
    refuse_unless(moved, image, "only a failed or finished Image can be read again")
    ocr_requested(session, image_id)
    return {"review_status": "pending"}


def transcription_out(transcription: Transcription) -> TranscriptionOut:
    return TranscriptionOut.model_validate(transcription, from_attributes=True)
