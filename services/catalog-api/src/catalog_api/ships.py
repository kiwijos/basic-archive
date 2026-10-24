import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session

from catalog_api.auth import staff_name
from catalog_api.dates import UncertainDate, present
from catalog_api.db import get_session, soft_delete
from catalog_api.events import record_changed
from catalog_api.models import Ship, Subject, SubjectName
from catalog_api.names import current_name
from catalog_api.source_keys import LIMIT, SourceKeyIn, flush_or_conflict, lookup_filter, refuse_if_taken
from catalog_api.relations import announce_counterparts

router = APIRouter(prefix="/api/catalog")


class ShipFacts(BaseModel):
    """What is recorded about a Ship, as last recorded."""

    ship_type: str | None = None
    tonnage: float | None = Field(default=None, ge=0, lt=100_000_000)
    launched: UncertainDate | None = None
    fate: str | None = None
    fate_date: UncertainDate | None = None


class ShipIn(ShipFacts, SourceKeyIn):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ShipOut(ShipFacts):
    id: uuid.UUID
    name: str | None
    created_by: str
    external_refs: list[dict]
    source_system: str | None
    source_id: str | None


def ship_out(session: Session, subject: Subject, ship: Ship) -> ShipOut:
    return ShipOut(
        id=subject.id,
        name=current_name(session, subject.id),
        created_by=subject.created_by,
        external_refs=subject.external_refs,
        source_system=subject.source_system,
        source_id=subject.source_id,
        ship_type=ship.ship_type,
        tonnage=ship.tonnage,
        launched=present(ship.launched),
        fate=ship.fate,
        fate_date=present(ship.fate_date),
    )


def find_ship(session: Session, ship_id: uuid.UUID, *, lock: bool = False) -> tuple[Subject, Ship]:
    """The Ship, or a 404. With `lock` its Subject row is locked until the transaction ends, so a change that
    reads a value and writes it back is not overwritten by another doing the same."""
    query = (
        select(Subject, Ship)
        .join(Ship, Ship.subject_id == Subject.id)
        .where(Subject.id == ship_id, Subject.deleted_at.is_(None))
    )
    if lock:
        query = query.with_for_update(of=Subject)
    row = session.execute(query).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Ship not found")
    return row


def apply_facts(ship: Ship, facts: ShipFacts) -> None:
    ship.ship_type = facts.ship_type
    ship.tonnage = facts.tonnage
    ship.launched = facts.launched
    ship.fate = facts.fate
    ship.fate_date = facts.fate_date


@router.post("/ships", status_code=201)
def create_ship(
    new: ShipIn,
    author: str = Depends(staff_name),
    session: Session = Depends(get_session),
) -> ShipOut:
    refuse_if_taken(session, Subject, new.source_system, new.source_id, "A Ship or Organisation")
    subject = Subject(kind="ship", created_by=author, source_system=new.source_system, source_id=new.source_id)
    session.add(subject)
    flush_or_conflict(session, new.source_system, new.source_id, "A Ship or Organisation")
    ship = Ship(subject_id=subject.id)
    apply_facts(ship, new)
    session.add(ship)
    session.add(SubjectName(subject_id=subject.id, name=new.name, created_by=author))
    session.flush()
    record_changed(session, subject)
    return ship_out(session, subject, ship)


@router.get("/ships", dependencies=[Depends(staff_name)])
def find_ships_by_source(
    key: tuple[str, str | None] = Depends(lookup_filter), session: Session = Depends(get_session)
) -> list[ShipOut]:
    """Ships that came from one source: one by its full key, or all of a system's, oldest first."""
    system, ident = key
    query = (
        select(Subject, Ship)
        .join(Ship, Ship.subject_id == Subject.id)
        .where(Subject.source_system == system, Subject.deleted_at.is_(None))
        .order_by(Subject.created_at)
        .limit(LIMIT)
    )
    if ident is not None:
        query = query.where(Subject.source_id == ident)
    return [ship_out(session, subject, ship) for subject, ship in session.execute(query)]


@router.get("/ships/{ship_id}", dependencies=[Depends(staff_name)])
def read_ship(ship_id: uuid.UUID, session: Session = Depends(get_session)) -> ShipOut:
    return ship_out(session, *find_ship(session, ship_id))


@router.put("/ships/{ship_id}", dependencies=[Depends(staff_name)])
def update_ship(
    ship_id: uuid.UUID, facts: ShipFacts, session: Session = Depends(get_session)
) -> ShipOut:
    subject, ship = find_ship(session, ship_id)
    apply_facts(ship, facts)
    session.flush()
    record_changed(session, subject)
    return ship_out(session, subject, ship)


@router.delete("/ships/{ship_id}", status_code=204, dependencies=[Depends(staff_name)])
def delete_ship(ship_id: uuid.UUID, session: Session = Depends(get_session)) -> None:
    subject, _ = find_ship(session, ship_id)
    announce_counterparts(session, subject)
    soft_delete(subject)
    record_changed(session, subject, "delete")
