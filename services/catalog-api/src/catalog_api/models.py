import uuid
from datetime import date, datetime

from sqlalchemy import ForeignKey, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, composite, mapped_column

from catalog_api.dates import UncertainDate


class Base(DeclarativeBase):
    pass


class Subject(Base):
    __tablename__ = "subject"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(Text)
    # Facts from other sources, each with where it came from, its identifier and when it was fetched.
    external_refs: Mapped[list] = mapped_column(JSONB, server_default="[]")
    # Where this record came from and its identifier there (see source_keys.py).
    source_system: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    deleted_at: Mapped[datetime | None]


class Ship(Base):
    __tablename__ = "ship"

    subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subject.id"), primary_key=True)
    ship_type: Mapped[str | None] = mapped_column(Text)
    tonnage: Mapped[float | None] = mapped_column(Numeric(10, 2))
    launched_date_text: Mapped[str | None]
    launched_date_from: Mapped[date | None]
    launched_date_to: Mapped[date | None]
    launched: Mapped[UncertainDate | None] = composite(
        UncertainDate, "launched_date_text", "launched_date_from", "launched_date_to"
    )
    fate: Mapped[str | None] = mapped_column(Text)
    fate_date_text: Mapped[str | None]
    fate_date_from: Mapped[date | None]
    fate_date_to: Mapped[date | None]
    fate_date: Mapped[UncertainDate | None] = composite(
        UncertainDate, "fate_date_text", "fate_date_from", "fate_date_to"
    )


class Outbox(Base):
    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB)
    published_at: Mapped[datetime | None]


class Document(Base):
    __tablename__ = "document"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text)
    document_type: Mapped[str | None] = mapped_column(Text)
    date_text: Mapped[str | None]
    date_from: Mapped[date | None]
    date_to: Mapped[date | None]
    period: Mapped[UncertainDate | None] = composite(
        UncertainDate, "date_text", "date_from", "date_to"
    )
    physical_location: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    source_system: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    deleted_at: Mapped[datetime | None]


class DocumentSubject(Base):
    __tablename__ = "document_subject"

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document.id"), primary_key=True)
    subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subject.id"), primary_key=True)
    role: Mapped[str | None] = mapped_column(Text)


class Transcription(Base):
    __tablename__ = "transcription"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    image_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("image.id"))
    source: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    engine: Mapped[str | None] = mapped_column(Text)
    engine_version: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Image(Base):
    __tablename__ = "image"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document.id"))
    page_no: Mapped[int]
    bucket: Mapped[str] = mapped_column(Text)
    object_key: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(Text)
    mime: Mapped[str] = mapped_column(Text)
    original_filename: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(Text)
    rights: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    deleted_at: Mapped[datetime | None]


class Organisation(Base):
    __tablename__ = "organisation"

    subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subject.id"), primary_key=True)
    organisation_type: Mapped[str | None] = mapped_column(Text)
    place: Mapped[str | None] = mapped_column(Text)


class Relation(Base):
    __tablename__ = "relation"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    from_subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subject.id"))
    predicate: Mapped[str] = mapped_column(Text)
    to_subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subject.id"))
    place: Mapped[str | None] = mapped_column(Text)
    date_text: Mapped[str | None]
    date_from: Mapped[date | None]
    date_to: Mapped[date | None]
    period: Mapped[UncertainDate | None] = composite(
        UncertainDate, "date_text", "date_from", "date_to"
    )
    source: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2))
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    deleted_at: Mapped[datetime | None]


class SubjectName(Base):
    __tablename__ = "subject_name"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subject.id"))
    name: Mapped[str] = mapped_column(Text)
    name_type: Mapped[str] = mapped_column(Text, default="given")
    date_text: Mapped[str | None]
    date_from: Mapped[date | None]
    date_to: Mapped[date | None]
    period: Mapped[UncertainDate | None] = composite(
        UncertainDate, "date_text", "date_from", "date_to"
    )
    source: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    deleted_at: Mapped[datetime | None]
