"""How an indexing view becomes a Meilisearch document."""

INDEX_OF = {"document": "documents", "ship": "subjects", "organisation": "subjects"}


def to_document(view: dict) -> dict:
    if view["entity"] == "document":
        return view
    return {
        "id": view["id"],
        "entity": view["entity"],
        "name": view["name"],
        # Every Name, so a search finds a ship by an old name; the details say when each was carried.
        "names": [name["name"] for name in view["names"]],
        "name_details": view["names"],
        "ship_type": view["ship_type"],
        "organisation_type": view["organisation_type"],
        "builders": view["builders"],
        "places": view["places"],
        "year_from": view["year_from"],
        "year_to": view["year_to"],
    }
