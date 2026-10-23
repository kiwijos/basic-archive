import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from catalog_api.auth import only_service
from catalog_api.contracts import validate
from catalog_api.db import get_session
from catalog_api.documents import document_fields, find_document
from catalog_api.models import Document, DocumentSubject, Organisation, Relation, Ship, Subject
from catalog_api.names import current_name, names_of
from catalog_api.organisations import find_organisation
from catalog_api.relations import live_relations
from catalog_api.ships import find_ship

MAX_PAGE = 100


def checked(view: dict) -> dict:
    """Refuse to serve a view that breaks the contract the indexer relies on."""
    validate("index.view", view)
    return view


router = APIRouter(prefix="/api/catalog/index", dependencies=[Depends(only_service("indexer"))])


def document_view(session: Session, document_id: uuid.UUID) -> dict:
    document = find_document(session, document_id)
    fields = document_fields(session, document)
    images = fields["images"]
    date = fields["date"]
    year_from, year_to = _years(date.date_from, date.date_to) if date else (None, None)
    ship_names: list[str] = []
    ship_types: list[str] = []
    builders: list[str] = []
    places: list[str] = []
    for link in fields["subjects"]:
        if link.kind != "ship":
            continue
        view = subject_view(session, "ship", link.subject_id)
        ship_names += [name["name"] for name in view["names"] if name["name"] not in ship_names]
        for target, values in ((ship_types, [view["ship_type"]]), (builders, view["builders"]), (places, view["places"])):
            target += [value for value in values if value and value not in target]
    return {
        "entity": "document",
        "id": str(fields["id"]),
        "title": fields["title"],
        "document_type": fields["document_type"],
        "description": fields["description"],
        "physical_location": fields["physical_location"],
        "date_text": date.date_text if date else None,
        "year_from": year_from,
        "year_to": year_to,
        "text": "\n\n".join(image.current_text for image in images if image.current_text),
        "verified": fields["verified"],
        "verified_images": fields["verified_images"],
        "image_count": fields["image_count"],
        "images": [{"id": str(image.id), "page_no": image.page_no} for image in images],
        "ship_names": ship_names,
        "ship_types": ship_types,
        "builders": builders,
        "places": places,
    }


def _years(period_from, period_to) -> tuple[int | None, int | None]:
    start, end = period_from, period_to
    if start is None and end is None:
        return None, None
    return (start or end).year, (end or start).year


def built_facts(session: Session, ship_id: uuid.UUID, ship: Ship) -> dict:
    """Builder, place and year of a Ship, derived from its built_by Relations.

    A Relation's own place wins over the builder's; the years come from the dated Relations, or
    else from the launch date.
    """
    builders: list[str] = []
    places: list[str] = []
    spans: list[tuple[int, int]] = []
    relations = session.scalars(
        live_relations(session, ship_id).where(
            Relation.predicate == "built_by", Relation.from_subject_id == ship_id
        )
    ).all()
    for relation in relations:
        name = current_name(session, relation.to_subject_id)
        if name and name not in builders:
            builders.append(name)
        place = relation.place or session.scalar(
            select(Organisation.place).where(Organisation.subject_id == relation.to_subject_id)
        )
        if place and place not in places:
            places.append(place)
        start, end = _years(relation.date_from, relation.date_to)
        if start is not None:
            spans.append((start, end))
    if not spans:
        start, end = _years(ship.launched_date_from, ship.launched_date_to)
        if start is not None:
            spans.append((start, end))
    return {
        "builders": builders,
        "places": places,
        "year_from": min((s[0] for s in spans), default=None),
        "year_to": max((s[1] for s in spans), default=None),
    }


def subject_view(session: Session, kind: Literal["ship", "organisation"], subject_id: uuid.UUID) -> dict:
    if kind == "ship":
        subject, ship = find_ship(session, subject_id)
        facts = {"ship_type": ship.ship_type, "organisation_type": None, **built_facts(session, subject_id, ship)}
    else:
        subject, organisation = find_organisation(session, subject_id)
        facts = {
            "ship_type": None,
            "organisation_type": organisation.organisation_type,
            "builders": [],
            "places": [organisation.place] if organisation.place else [],
            "year_from": None,
            "year_to": None,
        }
    current = current_name(session, subject.id)
    return {
        "entity": kind,
        "id": str(subject.id),
        "name": current,
        "names": [
            {
                "name": name.name,
                "name_type": name.name_type,
                "date_text": name.date_text,
                "date_from": name.date_from.isoformat() if name.date_from else None,
                "date_to": name.date_to.isoformat() if name.date_to else None,
                "current": name.name == current and name.name_type == "given",
            }
            for name in names_of(session, subject.id)
        ],
        **facts,
    }


@router.get("/document/{document_id}")
def read_document_view(document_id: uuid.UUID, session: Session = Depends(get_session)) -> dict:
    return checked(document_view(session, document_id))


@router.get("/{kind}/{subject_id}")
def read_subject_view(
    kind: Literal["ship", "organisation"], subject_id: uuid.UUID, session: Session = Depends(get_session)
) -> dict:
    return checked(subject_view(session, kind, subject_id))


@router.get("/{kind}")
def list_views(
    kind: Literal["document", "ship", "organisation"],
    after: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=MAX_PAGE),
    session: Session = Depends(get_session),
) -> dict:
    """Live records of one kind in id order, for rebuilding the index; `after` is the last id of the previous page."""
    if kind == "document":
        query = select(Document.id).where(Document.deleted_at.is_(None))
        column = Document.id
    else:
        query = select(Subject.id).where(Subject.kind == kind, Subject.deleted_at.is_(None))
        column = Subject.id
    if after is not None:
        query = query.where(column > after)
    ids = session.scalars(query.order_by(column).limit(limit + 1)).all()
    page = ids[:limit]
    items = [checked(document_view(session, i) if kind == "document" else subject_view(session, kind, i)) for i in page]
    return {"items": items, "next_after": str(page[-1]) if len(ids) > limit else None}

