"""Loads the demo data into catalog-api through its public HTTP API, and can be run again and again.

Every record is found by its source key before it is made, and every step looks at what is already there,
so a rerun, or a rerun after a crash half way, finishes the job and never makes a second copy.
"""

import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from archive_seed.accuracy import character_accuracy
from archive_seed.documents import DOCUMENTS, DocumentSeed
from archive_seed.fleet import ORGANISATIONS, SHIPS, SOURCE_SYSTEM, SYNTHETIC, Period
from archive_seed.plates import PLATE_DOCUMENTS, PLATES, PlateDocument, PlateUnavailable, fetch_plate
from archive_seed.plates import SOURCE_SYSTEM as PLATE_SYSTEM
from archive_seed.plates import Plate
from archive_seed.render import mime_of, render_page

logger = logging.getLogger(__name__)
API = "/api/catalog"
DRAWING_NOTE = "[Ritning utan löpande text]"  # what a person writes for a page that is a drawing with no running text
DEFAULT_CACHE = Path.home() / ".cache" / "archive-seed" / "plates"


class SeedError(Exception):
    """The seed cannot finish, for a reason a person has to know about."""


@dataclass(frozen=True)
class PageResult:
    """How one page was read. No accuracy means the OCR failed on it, which is not the same as reading it all wrong."""

    document: str
    page: int
    quality: str
    accuracy: float | None
    characters: int


@dataclass
class Report:
    created: Counter = field(default_factory=Counter)
    found: Counter = field(default_factory=Counter)
    pages: list[PageResult] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def _measured(self, quality: str | None = None) -> list[PageResult]:
        return [p for p in self.pages if p.accuracy is not None and (quality is None or p.quality == quality)]

    @staticmethod
    def _weighted(pages: list[PageResult]) -> float | None:
        """Accuracy over all the characters of these pages, so a long page counts for more than a short one."""
        total = sum(p.characters for p in pages)
        if not total:
            return None
        return 1 - sum((1 - p.accuracy) * p.characters for p in pages) / total

    def table(self) -> str:
        """The accuracy of the OCR, by quality of scan and overall, as lines of text for a person to read."""
        lines = ["Character accuracy of the machine reading (OCR) on the synthetic scans:"]
        for quality, accuracy in self.by_quality().items():
            count = len(self._measured(quality))
            lines.append(f"  {quality:<10}{count:>3} {'page' if count == 1 else 'pages':<6}{self._percent(accuracy):>9}")
        failed = [p for p in self.pages if p.accuracy is None]
        count = len(self._measured())
        note = f"  ({len(failed)} OCR failed)" if failed else ""
        lines.append(f"  {'all':<10}{count:>3} {'page' if count == 1 else 'pages':<6}{self._percent(self.overall()):>9}{note}")
        return "\n".join(lines)

    @staticmethod
    def _percent(accuracy: float | None) -> str:
        return "n/a" if accuracy is None else f"{accuracy * 100:.1f} %"

    def overall(self) -> float | None:
        return self._weighted(self._measured())

    def by_quality(self) -> dict[str, float | None]:
        return {q: self._weighted(self._measured(q)) for q in sorted({p.quality for p in self.pages})}


def _date(period: Period) -> dict:
    return {"date_text": period.text, "date_from": period.start, "date_to": period.end}


class Seeder:
    def __init__(
        self,
        api: httpx.Client,
        *,
        ocr_timeout: float = 300.0,
        poll: float = 1.0,
        cache_dir: Path = DEFAULT_CACHE,
        with_plates: bool = True,
        plates: dict[str, Plate] = PLATES,
        plate_documents: tuple[PlateDocument, ...] = PLATE_DOCUMENTS,
    ):
        self.api = api
        self.cache_dir = cache_dir
        self.with_plates = with_plates
        self.plates = plates
        self.plate_documents = plate_documents
        self.ocr_timeout = ocr_timeout
        self.poll = poll
        self.report = Report()
        self._ids: dict[str, str] = {}  # source key -> record id, for ships and organisations

    # ---- helpers ------------------------------------------------------------------------------------------------------

    def _call(self, method: str, path: str, **kwargs) -> httpx.Response:
        response = self.api.request(method, f"{API}{path}", **kwargs)
        return response

    def _expect(self, response: httpx.Response, what: str, *ok: int) -> httpx.Response:
        if response.status_code not in (ok or (200, 201)):
            raise SeedError(f"{what}: catalog-api answered {response.status_code}: {response.text[:300]}")
        return response

    def _lookup(self, kind: str, key: str, system: str = SOURCE_SYSTEM) -> dict | None:
        found = self._expect(
            self._call("GET", f"/{kind}", params={"source_system": system, "source_id": key}), f"looking up {key}", 200
        ).json()
        return found[0] if found else None

    def _ensure(self, kind: str, counter: str, key: str, body: dict) -> dict:
        """The record with this key, made now if it does not exist yet."""
        existing = self._lookup(kind, key)
        if existing is not None:
            self.report.found[counter] += 1
            return existing
        response = self._call("POST", f"/{kind}", json={**body, "source_system": SOURCE_SYSTEM, "source_id": key})
        if response.status_code == 409:
            existing = self._lookup(kind, key)  # made a moment ago by another run
            if existing is None:
                raise SeedError(f"{key} cannot be created: {response.json().get('detail')}")
            self.report.found[counter] += 1
            return existing
        self._expect(response, f"creating {key}", 201)
        self.report.created[counter] += 1
        return response.json()

    def seed(self) -> Report:
        self.seed_fleet()
        self.seed_documents()
        self.seed_readings()
        if self.with_plates:
            self.seed_plates()
        return self.report

    # ---- the fleet ----------------------------------------------------------------------------------------------------

    def seed_fleet(self) -> Report:
        for org in ORGANISATIONS:
            made = self._ensure("organisations", "organisations", org.key, {"name": org.name, "organisation_type": org.kind, "place": org.place})
            self._ids[org.key] = made["id"]
        for ship in SHIPS:
            made = self._ensure(
                "ships", "ships", ship.key,
                {
                    "name": ship.first_name, "ship_type": ship.ship_type, "tonnage": ship.tonnage, "launched": _date(ship.launched),
                    "fate": ship.fate, "fate_date": _date(ship.fate_date) if ship.fate_date else None,
                },
            )
            self._ids[ship.key] = made["id"]
            self._names(made["id"], ship)
        for ship in SHIPS:
            self._relations(self._ids[ship.key], ship)
        return self.report

    def _names(self, ship_id: str, ship) -> None:
        have = {n["name"] for n in self._expect(self._call("GET", f"/subjects/{ship_id}/names"), "reading names", 200).json()}
        for rename in ship.renames:  # in order: each new name closes the one before it
            if rename.name in have:
                self.report.found["names"] += 1
                continue
            self._expect(
                self._call("POST", f"/subjects/{ship_id}/names", json={"name": rename.name, "date": {"date_from": rename.starts}, "source": SYNTHETIC}),
                f"renaming {ship.key} to {rename.name}", 201,
            )
            self.report.created["names"] += 1

    def _relations(self, ship_id: str, ship) -> None:
        have = {
            (r["predicate"], r["from_subject_id"], r["to_subject_id"])
            for r in self._expect(self._call("GET", f"/subjects/{ship_id}/relations"), "reading relations", 200).json()
        }
        for relation in ship.relations:
            other = self._ids[relation.other]
            if (relation.predicate, ship_id, other) in have:
                self.report.found["relations"] += 1
                continue
            self._expect(
                self._call(
                    "POST", "/relations",
                    json={
                        "from_subject_id": ship_id, "predicate": relation.predicate, "to_subject_id": other,
                        "date": _date(relation.period), "place": relation.place, "source": SYNTHETIC,
                    },
                ),
                f"recording {ship.key} {relation.predicate} {relation.other}", 201,
            )
            self.report.created["relations"] += 1

    # ---- the documents ------------------------------------------------------------------------------------------------

    def seed_documents(self) -> Report:
        for seed in DOCUMENTS:
            document, fresh = self._document(seed)
            self._pages(document, seed, fresh)
            self._links(self._reread(document), seed)
        return self.report

    def _subject_id(self, key: str) -> str:
        if key not in self._ids:
            found = self._lookup("ships", key) or self._lookup("organisations", key)
            if found is None:
                raise SeedError(f"{key} is not in the archive: seed the fleet before the documents")
            self._ids[key] = found["id"]
        return self._ids[key]

    def _scan(self, seed: DocumentSeed, page_no: int) -> tuple[str, bytes, str]:
        mime = mime_of(seed.format)
        data = render_page(seed.pages[page_no - 1], font=seed.font, quality=seed.quality, fmt=seed.format, key=f"{seed.key}:{page_no}")
        return f"{seed.key}-{page_no}.{seed.format}", data, mime

    def _document(self, seed: DocumentSeed) -> tuple[dict, bool]:
        """The Document, and whether this call made it (with its first page)."""
        existing = self._lookup("documents", seed.key)
        if existing is not None:
            self.report.found["documents"] += 1
            return existing, False
        name, data, mime = self._scan(seed, 1)
        response = self._call(
            "POST", "/documents",
            data={
                "title": seed.title, "document_type": seed.kind, "rights": "CC0",
                "date_text": seed.date.text, "date_from": seed.date.start, "date_to": seed.date.end,
                "description": f"Synthetic demo document: fictional text written for this archive. Scan quality: {seed.quality}.",
                "source_system": SOURCE_SYSTEM, "source_id": seed.key,
            },
            files={"file": (name, data, mime)},
        )
        if response.status_code == 409:
            existing = self._lookup("documents", seed.key)
            if existing is None:
                raise SeedError(f"{seed.key} cannot be created: {response.json().get('detail')}")
            self.report.found["documents"] += 1
            return existing, False
        self._expect(response, f"uploading {seed.key}", 201)
        self.report.created["documents"] += 1
        self.report.created["pages"] += 1
        return response.json(), True

    def _reread(self, document: dict) -> dict:
        return self._expect(self._call("GET", f"/documents/{document['id']}"), "reading a document", 200).json()

    def _pages(self, document: dict, seed: DocumentSeed, fresh: bool) -> None:
        have = {image["page_no"] for image in self._reread(document)["images"]}
        for page_no in range(1, len(seed.pages) + 1):
            if page_no in have:
                if not fresh:
                    self.report.found["pages"] += 1
                continue
            name, data, mime = self._scan(seed, page_no)
            self._expect(
                self._call("POST", f"/documents/{document['id']}/images", data={"rights": "CC0"}, files={"file": (name, data, mime)}),
                f"adding page {page_no} to {seed.key}", 201,
            )
            self.report.created["pages"] += 1

    def _links(self, document: dict, seed: DocumentSeed) -> None:
        have = {link["subject_id"] for link in document["subjects"]}
        wanted = [(key, "about") for key in seed.ships] + [(key, "party") for key in seed.organisations]
        for key, role in wanted:
            subject_id = self._subject_id(key)
            if subject_id in have:
                self.report.found["links"] += 1
                continue
            self._expect(self._call("PUT", f"/documents/{document['id']}/subjects/{subject_id}", json={"role": role}), f"linking {seed.key} to {key}", 200, 201)
            self.report.created["links"] += 1

    # ---- readings: wait for the OCR, measure it, then have a person confirm what is meant to be confirmed --------------

    def seed_readings(self) -> Report:
        self._await_ocr()
        self.report.pages = self.measure_pages()
        made = self._seeded_documents()
        for seed in DOCUMENTS:
            images = sorted(made[seed.key]["images"], key=lambda image: image["page_no"])
            for image, text in zip(images, seed.pages):
                if self._should_verify(seed, image["page_no"]):
                    self._verify(image, text)
        return self.report

    def measure_pages(self) -> list[PageResult]:
        """How well the OCR read each seeded page. Changes nothing, and can be asked at any time: it compares the
        machine reading, which a person's later correction does not replace, with the text the scan was made from."""
        made = self._seeded_documents()
        results = []
        for seed in DOCUMENTS:
            images = sorted(made[seed.key]["images"], key=lambda image: image["page_no"])
            results += [self._measure(seed, image, text) for image, text in zip(images, seed.pages)]
        return results

    def _documents_of(self, system: str) -> dict[str, dict]:
        found = self._expect(self._call("GET", "/documents", params={"source_system": system}), f"listing the {system} documents", 200).json()
        return {d["source_id"]: d for d in found}

    def _seeded_documents(self) -> dict[str, dict]:
        made = self._documents_of(SOURCE_SYSTEM)
        missing = [d.key for d in DOCUMENTS if d.key not in made]
        if missing:
            raise SeedError(f"{missing[0]} is not in the archive: seed the documents before the readings")
        return made

    def _await_ocr(self, system: str = SOURCE_SYSTEM, keys: set[str] | None = None) -> None:
        """Nothing is verified before every page has been read, or has failed: a person's text on a page the worker has
        not reached yet would make the archive refuse the machine reading, and there would be nothing to measure."""
        deadline = time.monotonic() + self.ocr_timeout
        while True:
            waiting = [
                f"{key} p{image['page_no']}"
                for key, document in self._documents_of(system).items()
                if keys is None or key in keys
                for image in document["images"]
                if image["review_status"] == "pending"
            ]
            if not waiting:
                return
            if time.monotonic() >= deadline:
                raise SeedError(f"still waiting for OCR after {self.ocr_timeout:g} s on: {', '.join(waiting)}. Is transcribe-worker running?")
            time.sleep(self.poll)

    def _measure(self, seed: DocumentSeed, image: dict, reference: str) -> PageResult:
        transcriptions = self._expect(self._call("GET", f"/images/{image['id']}/transcriptions"), "reading transcriptions", 200).json()
        machine = next((t for t in transcriptions if t["source"] == "machine"), None)  # newest first
        accuracy = character_accuracy(reference, machine["text"]) if machine else None
        return PageResult(seed.key, image["page_no"], seed.quality, accuracy, len(" ".join(reference.split())))

    @staticmethod
    def _should_verify(seed: DocumentSeed, page_no: int) -> bool:
        return seed.state == "verified" or (seed.state == "partial" and page_no == 1)

    def _verify(self, image: dict, text: str) -> None:
        if image["verified"]:
            self.report.found["verified pages"] += 1
            return
        self._expect(
            self._call("POST", f"/images/{image['id']}/transcriptions", json={"source": "human", "text": text, "language": "swe"}),
            "verifying a page", 201,
        )
        self.report.created["verified pages"] += 1

    # ---- the plates: real drawings, fetched from Wikimedia Commons ----------------------------------------------------

    def seed_plates(self) -> Report:
        """Upload what is missing. A Document is only started once all its sheets are in hand, so an unreachable
        Commons leaves nothing half made, and a Document that is already complete needs no network at all."""
        done = []
        for document in self.plate_documents:
            if self._plate_document(document):
                done.append(document.key)
        self._await_ocr(PLATE_SYSTEM, set(done))
        for document in self._documents_of(PLATE_SYSTEM).values():
            if document["source_id"] in done:
                for image in document["images"]:
                    self._note_drawing(image)
        return self.report

    def _plate_document(self, seed: PlateDocument) -> bool:
        """True when the Document is complete in the archive; False when its sheets could not be fetched."""
        existing = self._lookup("documents", seed.key, PLATE_SYSTEM)
        have = {i["page_no"] for i in self._reread(existing)["images"]} if existing else set()
        missing = [n for n in range(1, len(seed.plates) + 1) if n not in have]
        if existing is not None:
            self.report.found["plate documents"] += 1
        if not missing:
            self.report.found["plate pages"] += len(have)
            return True
        try:
            files = {n: (self.plates[seed.plates[n - 1]], fetch_plate(self.plates[seed.plates[n - 1]], self.cache_dir)) for n in missing}
        except PlateUnavailable as error:
            message = f"{seed.key} was not loaded: {error}"
            logger.warning(message)
            self.report.skipped.append(message)
            return False
        for page_no in missing:
            plate, path = files[page_no]
            upload = {"file": (plate.title.removeprefix("File:").replace(" ", "_"), path.read_bytes(), plate.mime)}
            if existing is None:
                existing = self._expect(
                    self._call(
                        "POST", "/documents",
                        data={
                            "title": seed.title, "document_type": "drawing", "rights": "PDM", "description": seed.describe(self.plates),
                            "date_text": seed.date.text, "date_from": seed.date.start, "date_to": seed.date.end,
                            "source_system": PLATE_SYSTEM, "source_id": seed.key,
                        },
                        files=upload,
                    ),
                    f"uploading {seed.key}", 201,
                ).json()
                self.report.created["plate documents"] += 1
            else:
                self._expect(self._call("POST", f"/documents/{existing['id']}/images", data={"rights": "PDM"}, files=upload), f"adding sheet {page_no} to {seed.key}", 201)
            self.report.created["plate pages"] += 1
        return True

    def _note_drawing(self, image: dict) -> None:
        if image["verified"]:
            self.report.found["verified pages"] += 1
            return
        self._expect(
            self._call("POST", f"/images/{image['id']}/transcriptions", json={"source": "human", "text": DRAWING_NOTE, "language": "swe"}),
            "noting a drawing", 201,
        )
        self.report.created["verified pages"] += 1
