"""Turns Meilisearch hits into what the public API returns.

Highlights come back as parts, never as markup, so a client can show them with plain text nodes and
nothing from the archive can inject HTML.
"""

START, END = "\ue000", "\ue001"  # private-use characters that cannot occur in archive text


def parts(formatted: str | None) -> list[dict]:
    """Text with highlight markers becomes a list of {"text", "match"} pieces."""
    out, matched = [], False
    for piece in (formatted or "").replace(END, START).split(START):
        if piece:
            out.append({"text": piece, "match": matched})
        matched = not matched
    return out


def document_hit(hit: dict, iiif_base: str) -> dict:
    formatted = hit.get("_formatted", {})
    pages = [
        {"page_no": image["page_no"], "id": image["id"], "iiif_info": f"{iiif_base}/{image['id']}/info.json"}
        for image in hit.get("images", [])
    ]
    first = hit["images"][0]["id"] if hit.get("images") else None
    return {
        "id": hit["id"],
        "title": hit["title"],
        "document_type": hit.get("document_type"),
        "date_text": hit.get("date_text"),
        "year_from": hit.get("year_from"),
        "year_to": hit.get("year_to"),
        "verified": hit["verified"],
        "verified_images": hit["verified_images"],
        "image_count": hit["image_count"],
        "ship_names": hit.get("ship_names", []),
        "pages": pages,
        "thumbnail": f"{iiif_base}/{first}/full/!400,400/0/default.jpg" if first else None,
        "highlights": {"title": parts(formatted.get("title")), "text": parts(formatted.get("text"))},
    }


def plain(formatted: str) -> str:
    return formatted.replace(START, "").replace(END, "")


def subject_hit(hit: dict) -> dict:
    formatted = hit.get("_formatted", {})
    matched = next((entry for entry in formatted.get("names", []) if START in entry), None)
    return {
        "id": hit["id"],
        "entity": hit["entity"],
        "name": hit["name"],
        # Which of the names the Subject has carried is what the query matched, if it was a name at all.
        "matched_name": plain(matched) if matched else None,
        "names": [
            {k: detail[k] for k in ("name", "date_text", "date_from", "date_to", "current")}
            for detail in hit["name_details"]
        ],
        "ship_type": hit.get("ship_type"),
        "organisation_type": hit.get("organisation_type"),
        "builders": hit.get("builders", []),
        "places": hit.get("places", []),
        "year_from": hit.get("year_from"),
        "year_to": hit.get("year_to"),
        "highlights": {"name": parts(formatted.get("name")), "names": parts(matched) if matched else []},
    }


def document_landing(hit: dict, iiif_base: str) -> dict:
    """Everything a Document's own page shows."""
    return {
        "id": hit["id"],
        "title": hit["title"],
        "document_type": hit.get("document_type"),
        "description": hit.get("description"),
        "physical_location": hit.get("physical_location"),
        "date_text": hit.get("date_text"),
        "year_from": hit.get("year_from"),
        "year_to": hit.get("year_to"),
        "verified": hit["verified"],
        "verified_images": hit["verified_images"],
        "image_count": hit["image_count"],
        "images": [{**image, "iiif_info": f"{iiif_base}/{image['id']}/info.json"} for image in hit.get("images", [])],
        "subjects": hit.get("subjects", []),
    }


def subject_landing(hit: dict) -> dict:
    """Everything a Ship's or Organisation's own page shows."""
    return {
        "id": hit["id"],
        "entity": hit["entity"],
        "name": hit["name"],
        "names": [
            {k: detail[k] for k in ("name", "name_type", "date_text", "date_from", "date_to", "current")}
            for detail in hit["name_details"]
        ],
        "ship_type": hit.get("ship_type"),
        "organisation_type": hit.get("organisation_type"),
        "tonnage": hit.get("tonnage"),
        "launched": hit.get("launched"),
        "fate": hit.get("fate"),
        "fate_date": hit.get("fate_date"),
        "builders": hit.get("builders", []),
        "places": hit.get("places", []),
        "year_from": hit.get("year_from"),
        "year_to": hit.get("year_to"),
        "relations": hit.get("relations", []),
        "documents": hit.get("documents", []),
    }
