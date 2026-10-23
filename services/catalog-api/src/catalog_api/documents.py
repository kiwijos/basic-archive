import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, BeforeValidator, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from catalog_api.auth import staff_name, staff_or_service_name
from catalog_api.dates import UncertainDate, present
from catalog_api.db import get_session
from catalog_api.events import document_changed, ocr_requested
from catalog_api.models import Document, DocumentSubject, Image, Subject
from catalog_api.names import current_name, find_subject
from catalog_api.settings import Settings
from catalog_api.storage import ObjectStorage
from catalog_api.uploads import FileTooLarge, fingerprint, sniff_mime

router = APIRouter(prefix="/api/catalog")

Rights = Literal["CC0", "PDM", "CC BY", "reserved"]


def blank_to_none(value):
    """A browser form sends an empty string for every input the user left alone."""
    return None if isinstance(value, str) and not value.strip() else value


FormText = Annotated[str | None, BeforeValidator(blank_to_none), Form()]
FormDate = Annotated[date | None, BeforeValidator(blank_to_none), Form()]


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_storage(request: Request) -> ObjectStorage:
    return request.app.state.storage


class ImageOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    page_no: int
    mime: str
    sha256: str
    original_filename: str | None
    rights: str
    review_status: str


class SubjectLinkIn(BaseModel):
    role: str | None = None


class SubjectLinkOut(BaseModel):
    subject_id: uuid.UUID
    kind: str
    name: str | None
    role: str | None


class DocumentOut(BaseModel):
    id: uuid.UUID
    title: str
    document_type: str | None
    date: UncertainDate | None
    physical_location: str | None
    description: str | None
    created_by: str
    images: list[ImageOut]
    subjects: list[SubjectLinkOut]


class UploadOut(DocumentOut):
    # Set when the same bytes were uploaded before; the new Document is still created.
    duplicate_of_image_id: uuid.UUID | None


def image_out(image: Image) -> ImageOut:
    return ImageOut.model_validate(image, from_attributes=True)


def link_out(session: Session, subject: Subject, role: str | None) -> SubjectLinkOut:
    return SubjectLinkOut(
        subject_id=subject.id,
        kind=subject.kind,
        name=current_name(session, subject.id),
        role=role,
    )


def links_of(session: Session, document_id: uuid.UUID) -> list[SubjectLinkOut]:
    rows = session.execute(
        select(DocumentSubject, Subject)
        .join(Subject, Subject.id == DocumentSubject.subject_id)
        .where(DocumentSubject.document_id == document_id, Subject.deleted_at.is_(None))
    ).all()
    links = [link_out(session, subject, link.role) for link, subject in rows]
    return sorted(links, key=lambda link: (link.kind, link.name or ""))


def document_fields(session: Session, document: Document) -> dict:
    images = session.scalars(
        select(Image)
        .where(Image.document_id == document.id, Image.deleted_at.is_(None))
        .order_by(Image.page_no)
    )
    return {
        "id": document.id,
        "title": document.title,
        "document_type": document.document_type,
        "date": present(document.period),
        "physical_location": document.physical_location,
        "description": document.description,
        "created_by": document.created_by,
        "images": [image_out(image) for image in images],
        "subjects": links_of(session, document.id),
    }


def find_document(session: Session, document_id: uuid.UUID) -> Document:
    document = session.scalars(
        select(Document).where(Document.id == document_id, Document.deleted_at.is_(None))
    ).one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("/documents/{document_id}", dependencies=[Depends(staff_name)])
def read_document(document_id: uuid.UUID, session: Session = Depends(get_session)) -> DocumentOut:
    return DocumentOut(**document_fields(session, find_document(session, document_id)))


@router.put(
    "/documents/{document_id}/subjects/{subject_id}", dependencies=[Depends(staff_name)]
)
def link_subject(
    document_id: uuid.UUID,
    subject_id: uuid.UUID,
    new: SubjectLinkIn,
    session: Session = Depends(get_session),
) -> SubjectLinkOut:
    document = find_document(session, document_id)
    subject = find_subject(session, subject_id)
    link = session.get(DocumentSubject, (document.id, subject.id))
    if link is None:
        link = DocumentSubject(document_id=document.id, subject_id=subject.id)
        session.add(link)
    link.role = new.role
    session.flush()
    document_changed(session, document)
    return link_out(session, subject, link.role)


class DownloadAddress(BaseModel):
    url: str
    expires_in: int


def find_image(session: Session, image_id: uuid.UUID) -> Image:
    image = session.scalars(
        select(Image).where(Image.id == image_id, Image.deleted_at.is_(None))
    ).one_or_none()
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found")
    return image


@router.get("/images/{image_id}", dependencies=[Depends(staff_or_service_name)])
def read_image(image_id: uuid.UUID, session: Session = Depends(get_session)) -> ImageOut:
    return image_out(find_image(session, image_id))


@router.get("/images/{image_id}/download-url", dependencies=[Depends(staff_or_service_name)])
def download_url(
    image_id: uuid.UUID,
    expires_in: Annotated[int | None, Query(ge=1, le=3600)] = None,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    storage: ObjectStorage = Depends(get_storage),
) -> DownloadAddress:
    image = find_image(session, image_id)
    lifetime = expires_in or settings.download_url_seconds
    return DownloadAddress(
        url=storage.download_url(image.bucket, image.object_key, lifetime), expires_in=lifetime
    )


@router.post("/documents", status_code=201)
def upload_document(
    file: UploadFile,
    title: Annotated[str, Form(max_length=500)],
    document_type: FormText = None,
    date_text: FormText = None,
    date_from: FormDate = None,
    date_to: FormDate = None,
    physical_location: FormText = None,
    description: FormText = None,
    rights: Annotated[Rights, Form()] = "reserved",
    author: str = Depends(staff_name),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    storage: ObjectStorage = Depends(get_storage),
) -> UploadOut:
    if not title.strip():
        raise HTTPException(status_code=422, detail="A Document needs a title")
    try:
        period = present(UncertainDate(date_text, date_from, date_to))
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=error.errors()[0]["msg"]) from error

    mime = sniff_mime(file.file)
    if mime is None:
        raise HTTPException(
            status_code=415,
            detail="Only TIFF, JPEG and PNG files are accepted. Convert PDF and HEIC files first.",
        )
    try:
        sha256 = fingerprint(file.file, settings.max_upload_bytes)
    except FileTooLarge:
        raise HTTPException(
            status_code=413,
            detail=f"The file is larger than the {settings.max_upload_bytes} byte limit",
        )

    duplicate_of = session.scalars(
        select(Image.id)
        .where(Image.sha256 == sha256, Image.deleted_at.is_(None))
        .order_by(Image.created_at)
        .limit(1)
    ).first()

    # The file goes first: if storage fails nothing is recorded, and an object whose rows
    # never got committed is an unreferenced leftover, not a broken record.
    image_id = uuid.uuid4()
    storage.put(settings.masters_bucket, str(image_id), file.file, mime)

    document = Document(
        title=title.strip(),
        document_type=document_type,
        period=period,
        physical_location=physical_location,
        description=description,
        created_by=author,
    )
    session.add(document)
    session.flush()
    session.add(
        Image(
            id=image_id,
            document_id=document.id,
            page_no=1,
            bucket=settings.masters_bucket,
            object_key=str(image_id),
            sha256=sha256,
            mime=mime,
            original_filename=file.filename,
            review_status="pending",
            rights=rights,
            created_by=author,
        )
    )
    session.flush()
    document_changed(session, document)
    ocr_requested(session, image_id)
    return UploadOut(**document_fields(session, document), duplicate_of_image_id=duplicate_of)
