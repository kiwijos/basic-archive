import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, BeforeValidator, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from catalog_api.auth import staff_name, staff_or_service_name
from catalog_api.dates import UncertainDate, present
from catalog_api.db import get_session
from catalog_api.events import document_changed, ocr_requested
from catalog_api.models import Document, DocumentSubject, Image, Subject
from catalog_api.names import current_name, find_subject
from catalog_api.verification import Reading, readings_of
from catalog_api.settings import Settings
from catalog_api.source_keys import LIMIT, flush_or_conflict, key_from_form, lookup_filter, refuse_if_taken
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


class ImageRecord(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    page_no: int
    mime: str
    sha256: str
    original_filename: str | None
    rights: str
    review_status: str


class ImageOut(ImageRecord):
    # Worked out from the Image's Transcriptions, see verification.py.
    verified: bool
    text_source: str | None
    current_text: str | None


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
    # A Document is verified only when every one of its Images is.
    verified: bool
    verified_images: int
    image_count: int
    source_system: str | None
    source_id: str | None


class UploadOut(DocumentOut):
    # Set when the same bytes were uploaded before; the new Document is still created.
    duplicate_of_image_id: uuid.UUID | None


def image_out(image: Image, reading: Reading) -> ImageOut:
    record = ImageRecord.model_validate(image, from_attributes=True)
    return ImageOut(
        **record.model_dump(),
        verified=reading.verified,
        text_source=reading.text_source,
        current_text=reading.current_text,
    )


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
    ).all()
    readings = readings_of(session, [image.id for image in images])
    pages = [image_out(image, readings[image.id]) for image in images]
    verified_pages = sum(page.verified for page in pages)
    return {
        "id": document.id,
        "title": document.title,
        "document_type": document.document_type,
        "date": present(document.period),
        "physical_location": document.physical_location,
        "description": document.description,
        "created_by": document.created_by,
        "images": pages,
        "subjects": links_of(session, document.id),
        "verified": bool(pages) and verified_pages == len(pages),
        "verified_images": verified_pages,
        "image_count": len(pages),
        "source_system": document.source_system,
        "source_id": document.source_id,
    }


def find_document(session: Session, document_id: uuid.UUID) -> Document:
    document = session.scalars(
        select(Document).where(Document.id == document_id, Document.deleted_at.is_(None))
    ).one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("/documents", dependencies=[Depends(staff_name)])
def find_documents_by_source(
    key: tuple[str, str | None] = Depends(lookup_filter), session: Session = Depends(get_session)
) -> list[DocumentOut]:
    """Documents that came from one source: one by its full key, or all of a system's, oldest first."""
    system, ident = key
    query = (
        select(Document)
        .where(Document.source_system == system, Document.deleted_at.is_(None))
        .order_by(Document.created_at)
        .limit(LIMIT)
    )
    if ident is not None:
        query = query.where(Document.source_id == ident)
    return [DocumentOut(**document_fields(session, document)) for document in session.scalars(query)]


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
    image = find_image(session, image_id)
    return image_out(image, readings_of(session, [image.id])[image.id])


@router.get("/images/{image_id}/content", dependencies=[Depends(staff_name)])
def read_image_content(
    image_id: uuid.UUID,
    session: Session = Depends(get_session),
    storage: ObjectStorage = Depends(get_storage),
) -> StreamingResponse:
    """The original file, so a browser can show the page. Garage is not reachable from a browser."""
    image = find_image(session, image_id)
    return StreamingResponse(
        storage.stream(image.bucket, image.object_key),
        media_type=image.mime,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": "inline",
        },
    )


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


def inspect_upload(file: UploadFile, settings: Settings) -> tuple[str, str]:
    """The MIME type and SHA-256 of an uploaded file, or an HTTP refusal if it is not acceptable."""
    mime = sniff_mime(file.file)
    if mime is None:
        raise HTTPException(
            status_code=415,
            detail="Only TIFF, JPEG and PNG files are accepted. Convert PDF and HEIC files first.",
        )
    try:
        return mime, fingerprint(file.file, settings.max_upload_bytes)
    except FileTooLarge:
        raise HTTPException(
            status_code=413,
            detail=f"The file is larger than the {settings.max_upload_bytes} byte limit",
        )


def earlier_upload_of(session: Session, sha256: str) -> uuid.UUID | None:
    return session.scalars(
        select(Image.id)
        .where(Image.sha256 == sha256, Image.deleted_at.is_(None))
        .order_by(Image.created_at)
        .limit(1)
    ).first()


def store_page(
    session: Session,
    storage: ObjectStorage,
    settings: Settings,
    document: Document,
    file: UploadFile,
    mime: str,
    sha256: str,
    rights: str,
    page_no: int,
    author: str,
) -> None:
    """Keep the file, record its Image as the next page, and queue it for OCR."""
    # The file goes first: if storage fails nothing is recorded, and an object whose rows
    # never got committed is an unreferenced leftover, not a broken record.
    image_id = uuid.uuid4()
    storage.put(settings.masters_bucket, str(image_id), file.file, mime)
    session.add(
        Image(
            id=image_id,
            document_id=document.id,
            page_no=page_no,
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


@router.post("/documents/{document_id}/images", status_code=201)
def add_page(
    document_id: uuid.UUID,
    file: UploadFile,
    rights: Annotated[Rights, Form()] = "reserved",
    author: str = Depends(staff_name),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    storage: ObjectStorage = Depends(get_storage),
) -> UploadOut:
    """Add another page to a Document. Locking the Document keeps two uploads from taking the same page number."""
    find_document(session, document_id)
    document = session.scalars(select(Document).where(Document.id == document_id).with_for_update()).one()
    mime, sha256 = inspect_upload(file, settings)
    duplicate_of = earlier_upload_of(session, sha256)
    last_page = session.scalar(
        select(func.max(Image.page_no)).where(Image.document_id == document_id, Image.deleted_at.is_(None))
    )
    store_page(session, storage, settings, document, file, mime, sha256, rights, (last_page or 0) + 1, author)
    return UploadOut(**document_fields(session, document), duplicate_of_image_id=duplicate_of)


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
    source_system: FormText = None,
    source_id: FormText = None,
    author: str = Depends(staff_name),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    storage: ObjectStorage = Depends(get_storage),
) -> UploadOut:
    system, ident = key_from_form(source_system, source_id)
    if not title.strip():
        raise HTTPException(status_code=422, detail="A Document needs a title")
    try:
        period = present(UncertainDate(date_text, date_from, date_to))
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=error.errors()[0]["msg"]) from error

    mime, sha256 = inspect_upload(file, settings)
    duplicate_of = earlier_upload_of(session, sha256)
    refuse_if_taken(session, Document, system, ident, "A Document")

    document = Document(
        title=title.strip(),
        document_type=document_type,
        period=period,
        physical_location=physical_location,
        description=description,
        source_system=system,
        source_id=ident,
        created_by=author,
    )
    session.add(document)
    flush_or_conflict(session, system, ident, "A Document")
    store_page(session, storage, settings, document, file, mime, sha256, rights, 1, author)
    return UploadOut(**document_fields(session, document), duplicate_of_image_id=duplicate_of)
