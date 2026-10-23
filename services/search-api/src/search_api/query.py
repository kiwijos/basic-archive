"""Builds Meilisearch requests from validated public parameters.

Every value from a client reaches Meilisearch as a quoted, escaped string or a checked integer, so
nothing a client sends can change the shape of a filter.
"""

from dataclasses import dataclass, field

from search_api import results

# Public parameter -> field in each index.
DOCUMENT_FIELDS = {"ship_type": "ship_types", "builder": "builders", "place": "places", "document_type": "document_type"}
SUBJECT_FIELDS = {"kind": "entity", "ship_type": "ship_type", "builder": "builders", "place": "places"}

FACETS = {
    "documents": ["ship_types", "builders", "places", "verified", "document_type"],
    "subjects": ["entity", "ship_type", "builders", "places", "organisation_type"],
}


def quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass
class Search:
    scope: str  # "documents" or "subjects"
    q: str = ""
    filters: dict[str, list[str]] = field(default_factory=dict)  # public parameter -> values
    verified_only: bool = False
    year_from: int | None = None
    year_to: int | None = None
    page: int = 1
    page_size: int = 20

    def meili_filter(self) -> list:
        fields = DOCUMENT_FIELDS if self.scope == "documents" else SUBJECT_FIELDS
        clauses: list = []
        for parameter, values in self.filters.items():
            if values:
                # A list inside the list means OR; separate entries mean AND.
                clauses.append([f"{fields[parameter]} = {quote(value)}" for value in values])
        if self.verified_only and self.scope == "documents":
            clauses.append("verified = true")
        # A record matches when the years it covers overlap the asked-for range.
        if self.year_from is not None:
            clauses.append(f"year_to >= {int(self.year_from)}")
        if self.year_to is not None:
            clauses.append(f"year_from <= {int(self.year_to)}")
        return clauses

    def body(self, *, hits: bool = True) -> dict:
        body = {
            "q": self.q,
            "filter": self.meili_filter(),
            "facets": FACETS[self.scope],
            "page": self.page,
            "hitsPerPage": self.page_size if hits else 0,
            "highlightPreTag": results.START,
            "highlightPostTag": results.END,
        }
        if self.scope == "documents":
            body.update(attributesToHighlight=["title", "text"], attributesToCrop=["text"], cropLength=30)
        else:
            body["attributesToHighlight"] = ["name", "names"]
        return body
