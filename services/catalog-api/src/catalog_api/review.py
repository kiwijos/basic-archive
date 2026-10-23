import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from catalog_api.auth import staff_name
from catalog_api.db import get_session

router = APIRouter(prefix="/api/catalog")

# One row per Document that still has an Image without a Human transcription, oldest first.
# "Verified" is read from the Transcriptions, the same rule as verification.py.
QUEUE = text(
    """
    WITH page AS (
        SELECT i.document_id, i.review_status,
               EXISTS (SELECT 1 FROM transcription t WHERE t.image_id = i.id AND t.source = 'human') AS verified
        FROM image i
        WHERE i.deleted_at IS NULL
    )
    SELECT d.id, d.title, d.document_type, d.created_at,
           count(*) AS image_count,
           count(*) FILTER (WHERE p.verified) AS verified_images,
           count(*) FILTER (WHERE p.review_status = 'pending') AS pending,
           count(*) FILTER (WHERE p.review_status = 'ocr_done') AS ocr_done,
           count(*) FILTER (WHERE p.review_status = 'failed') AS failed,
           count(*) FILTER (WHERE p.review_status = 'verified') AS verified
    FROM document d
    JOIN page p ON p.document_id = d.id
    WHERE d.deleted_at IS NULL
    GROUP BY d.id
    HAVING count(*) FILTER (WHERE p.verified) < count(*)
    ORDER BY d.created_at, d.id
    LIMIT :limit OFFSET :offset
    """
)


class QueueItem(BaseModel):
    id: uuid.UUID
    title: str
    document_type: str | None
    created_at: datetime
    verified_images: int
    image_count: int
    # How many of its Images are in each Review status.
    statuses: dict[str, int]


class WhoAmI(BaseModel):
    name: str


@router.get("/review-queue")
def review_queue(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    _: str = Depends(staff_name),
    session: Session = Depends(get_session),
) -> list[QueueItem]:
    """The Documents that are not fully verified, including partly verified ones."""
    rows = session.execute(QUEUE, {"limit": limit, "offset": offset}).all()
    return [
        QueueItem(
            id=row.id,
            title=row.title,
            document_type=row.document_type,
            created_at=row.created_at,
            verified_images=row.verified_images,
            image_count=row.image_count,
            statuses={
                "pending": row.pending,
                "ocr_done": row.ocr_done,
                "failed": row.failed,
                "verified": row.verified,
            },
        )
        for row in rows
    ]


@router.get("/me")
def who_am_i(name: str = Depends(staff_name)) -> WhoAmI:
    """Lets a client check a token and show who it belongs to."""
    return WhoAmI(name=name)
