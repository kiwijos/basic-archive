import uuid
from datetime import date, datetime

from sqlalchemy import ForeignKey, Numeric, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Subject(Base):
    __tablename__ = "subject"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    deleted_at: Mapped[datetime | None]


class Ship(Base):
    __tablename__ = "ship"

    subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subject.id"), primary_key=True)
    ship_type: Mapped[str | None] = mapped_column(Text)
    tonnage: Mapped[float | None] = mapped_column(Numeric(10, 2))


class SubjectName(Base):
    __tablename__ = "subject_name"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subject.id"))
    name: Mapped[str] = mapped_column(Text)
    name_type: Mapped[str] = mapped_column(Text, default="given")
    date_to: Mapped[date | None]
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    deleted_at: Mapped[datetime | None]
