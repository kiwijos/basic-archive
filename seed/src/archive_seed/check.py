"""The demo check: does the archive show what the seed was meant to leave in it? It only reads.

It asks the way a visitor does (public search, the IIIF image server) as well as the way staff do, since the point
of the demo is that a seeded Document can be found, opened and zoomed into. The index and the OCR run behind the
API, so what has not shown up yet is waited for, within a limit, before it is called missing.
"""

import time
from dataclasses import dataclass

import httpx

from archive_seed.documents import DOCUMENTS
from archive_seed.fleet import ORGANISATIONS, SHIPS, SOURCE_SYSTEM
from archive_seed.loader import API, PageResult, SeedError, Seeder
from archive_seed.plates import PLATE_DOCUMENTS
from archive_seed.plates import SOURCE_SYSTEM as PLATE_SYSTEM

OLD_NAME_SHIP = "ship-nordstjarnan"
REBUILT_SHIP = "ship-alvdrottningen"


@dataclass(frozen=True)
class Finding:
    name: str
    outcome: str  # ok, FAIL or skip
    detail: str = ""

    def __str__(self) -> str:
        return f"  {self.outcome:<4} {self.name}" + (f": {self.detail}" if self.detail else "")


class Unreadable(Exception):
    """The archive refused or failed a question the check needs answered."""


class Check:
    def __init__(self, staff: httpx.Client, public: httpx.Client, *, index_wait: float = 90.0):
        self.staff, self.public, self.index_wait = staff, public, index_wait
        self.findings: list[Finding] = []
        self.pages: list[PageResult] = []

    @property
    def failed(self) -> bool:
        return any(f.outcome == "FAIL" for f in self.findings)

    def _add(self, name: str, ok: bool | None, detail: str = "") -> bool:
        self.findings.append(Finding(name, "skip" if ok is None else "ok" if ok else "FAIL", detail))
        return bool(ok)

    def _get(self, client: httpx.Client, path: str, **params) -> httpx.Response:
        return client.get(path, params=params)

    def _list(self, kind: str, system: str) -> dict[str, dict]:
        response = self._get(self.staff, f"{API}/{kind}", source_system=system)
        if response.status_code != 200:
            raise Unreadable(f"listing {kind} answered {response.status_code}: {response.text[:200]}")
        return {item["source_id"]: item for item in response.json()}

    def _eventually(self, test) -> str | None:
        """None as soon as `test` is satisfied; otherwise what it last complained about, once the wait is over."""
        deadline, problem = time.monotonic() + self.index_wait, "never tried"
        while True:
            problem = test()
            if problem is None or time.monotonic() >= deadline:
                return problem
            time.sleep(1)

    def run(self) -> list[Finding]:
        try:
            ships, firms = self._list("ships", SOURCE_SYSTEM), self._list("organisations", SOURCE_SYSTEM)
            documents, plates = self._list("documents", SOURCE_SYSTEM), self._list("documents", PLATE_SYSTEM)
        except (Unreadable, httpx.HTTPError) as error:
            self._add("the archive can be read", False, str(error))
            return self.findings
        self._records(ships, firms, documents)
        self._states(documents)
        self._history(ships)
        self._found(ships, firms, documents)
        self._old_name(ships)
        self._viewable(documents, plates)
        self._accuracy()
        return self.findings

    def _records(self, ships, firms, documents) -> None:
        wanted = {"ships": len(SHIPS), "organisations": len(ORGANISATIONS), "documents": len(DOCUMENTS)}
        got = {"ships": len(ships), "organisations": len(firms), "documents": len(documents)}
        self._add("the seeded records are all there", got == wanted, ", ".join(f"{got[k]}/{wanted[k]} {k}" for k in wanted))

    def _states(self, documents) -> None:
        verified = [k for k, d in documents.items() if d["verified"]]
        machine = [k for k, d in documents.items() if d["verified_images"] == 0]
        partly = [k for k, d in documents.items() if 0 < d["verified_images"] < d["image_count"]]
        self._add(
            "there are verified, machine-only and partly verified documents",
            bool(verified and machine and partly),
            f"{len(verified)} verified, {len(machine)} machine-only, {len(partly)} partly verified",
        )

    def _history(self, ships) -> None:
        ship, rebuilt = ships.get(OLD_NAME_SHIP), ships.get(REBUILT_SHIP)
        if not (ship and rebuilt):
            self._add("a ship has several names and a rebuilt hull links back to it", False, "the ships are not there")
            return
        names = self._get(self.staff, f"{API}/subjects/{ship['id']}/names").json()
        links = self._get(self.staff, f"{API}/subjects/{rebuilt['id']}/relations", predicate="rebuilt_from").json()
        linked = any(link["to_subject_id"] == ship["id"] for link in links)
        self._add("a ship has several names and a rebuilt hull links back to it", len(names) >= 3 and linked, f"{len(names)} names, rebuilt-from {'linked' if linked else 'missing'}")

    def _found(self, ships, firms, documents) -> None:
        def missing() -> str | None:
            absent = [
                key
                for kind, records in (("documents", documents), ("subjects", {**ships, **firms}))
                for key, record in records.items()
                if self._get(self.public, f"/api/search/{kind}/{record['id']}").status_code != 200
            ]
            return f"not in the search index yet: {', '.join(absent)}" if absent else None

        problem = self._eventually(missing)
        self._add("every seeded record can be opened from the public search index", problem is None, problem or f"{len(documents) + len(ships) + len(firms)} records")

    def _old_name(self, ships) -> None:
        ship = ships.get(OLD_NAME_SHIP)
        old = next(s.first_name for s in SHIPS if s.key == OLD_NAME_SHIP)

        def finds() -> str | None:
            hits = self._get(self.public, "/api/search/subjects", q=old, kind="ship").json()["hits"]
            hit = next((h for h in hits if ship and h["id"] == ship["id"]), None)
            if hit is None:
                return f"a search for the old name {old} does not find the ship"
            return None if hit["matched_name"] == old and hit["name"] != old else f"matched {hit['matched_name']!r}, known today as {hit['name']!r}"

        problem = self._eventually(finds)
        self._add("an old name finds the ship, which is known by its latest", problem is None, problem or old)

    def _zooms(self, image_id: str, *, wide: bool) -> str | None:
        info = self.public.get(f"/iiif/3/{image_id}/info.json")
        if info.status_code != 200:
            return f"info.json answered {info.status_code}"
        width = info.json()["width"]
        if wide and width < 2000:
            return f"only {width} px wide, too small to zoom into"
        tile = self.public.get(f"/iiif/3/{image_id}/0,0,{min(512, width)},{min(512, width)}/256,/0/default.jpg")
        if tile.status_code != 200 or tile.headers.get("content-type") != "image/jpeg":
            return f"a tile answered {tile.status_code} {tile.headers.get('content-type')}"
        return None

    def _viewable(self, documents, plates) -> None:
        first = next(iter(documents.values()), None)
        problem = self._zooms(first["images"][0]["id"], wide=False) if first else "there is no document"
        self._add("a seeded scan is served by the image server", problem is None, problem or first["source_id"])
        if not plates:
            self._add("a plate zooms", None, "the plates were not loaded (offline?). Run it again when there is a network")
            return
        plate = plates.get(PLATE_DOCUMENTS[0].key)
        problem = self._zooms(plate["images"][0]["id"], wide=True) if plate else f"{PLATE_DOCUMENTS[0].key} is missing"
        self._add("a plate zooms: a large public-domain drawing is served in tiles", problem is None, problem or plate["title"])

    def _accuracy(self) -> None:
        try:
            pages = Seeder(self.staff).measure_pages()
        except (SeedError, httpx.HTTPError) as error:  # reported, not raised: the other checks still count
            self._add("the OCR accuracy can be measured", False, str(error))
            return
        measured = [p for p in pages if p.accuracy is not None]
        self._add("the OCR accuracy is measured on every page", len(measured) == len(pages) > 0, f"{len(measured)} of {len(pages)} pages")
        self.pages = pages
