import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from sqlalchemy.orm import Session

from catalog_api.auth import staff_name
from catalog_api.db import get_session
from catalog_api.events import record_changed
from catalog_api.names import current_name
from catalog_api.ships import find_ship
from catalog_api.wikidata import QID, WikidataClient, entity_url

router = APIRouter(prefix="/api/catalog")


def wikidata_client(request: Request) -> WikidataClient:
    return request.app.state.wikidata


@router.get("/ships/{ship_id}/wikidata-candidates", dependencies=[Depends(staff_name)])
def list_candidates(
    ship_id: uuid.UUID,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    session: Session = Depends(get_session),
    wikidata: WikidataClient = Depends(wikidata_client),
) -> dict:
    """Items on Wikidata that might be this Ship. Nothing is stored: a person picks one in a second step."""
    subject, _ = find_ship(session, ship_id)
    name = q or current_name(session, subject.id) or ""
    return {"query": name, "candidates": [candidate.as_dict() for candidate in wikidata.search(name)]}


@router.put("/ships/{ship_id}/wikidata/{qid}")
def choose_match(
    ship_id: uuid.UUID,
    qid: Annotated[str, Path(pattern=QID.pattern)],
    author: str = Depends(staff_name),
    session: Session = Depends(get_session),
    wikidata: WikidataClient = Depends(wikidata_client),
) -> dict:
    """Store the Wikidata item a person chose for this Ship. The item is read from Wikidata here, so what is
    stored is what Wikidata says and when it was fetched, never text supplied by the caller."""
    subject, _ = find_ship(session, ship_id)
    item = wikidata.entity(qid)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Wikidata has no item {qid}")
    reference = {
        "source": "wikidata",
        "id": item.id,
        "label": item.label,
        "description": item.description,
        "url": entity_url(item.id),
        "retrieved_at": datetime.now(UTC).isoformat(),
        "chosen_by": author,
    }
    # A new list, so the change is seen; choosing the same item again replaces its entry.
    subject.external_refs = [
        ref for ref in subject.external_refs if not (ref.get("source") == "wikidata" and ref.get("id") == item.id)
    ] + [reference]
    session.flush()
    record_changed(session, subject)
    return reference


@router.delete("/ships/{ship_id}/wikidata/{qid}", status_code=204, dependencies=[Depends(staff_name)])
def remove_match(
    ship_id: uuid.UUID,
    qid: Annotated[str, Path(pattern=QID.pattern)],
    session: Session = Depends(get_session),
) -> None:
    """Undo a choice. Nothing is asked of Wikidata, so a wrong match can be removed during an outage."""
    subject, _ = find_ship(session, ship_id)
    kept = [ref for ref in subject.external_refs if not (ref.get("source") == "wikidata" and ref.get("id") == qid)]
    if len(kept) == len(subject.external_refs):
        raise HTTPException(status_code=404, detail=f"{qid} is not stored on this Ship")
    subject.external_refs = kept
    session.flush()
    record_changed(session, subject)
