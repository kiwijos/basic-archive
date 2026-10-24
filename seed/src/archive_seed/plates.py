"""Public-domain ship plans from Wikimedia Commons, and how they are fetched.

The plates are four of Fredrik Henrik af Chapman's plates from "Architectura Navalis Mercatoria" (Stockholm,
1768). Chapman was a Swedish naval architect who died in 1808, so the rights in his work have run out and
Commons files them as public domain. They are not kept in this repository: they are fetched by exact address,
checked against a SHA-256 recorded here, and kept in a local cache. The SHA-1 is what Commons itself
reports for each file, recorded as evidence that these are the files that were looked at.
"""

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from archive_seed.fleet import Period

logger = logging.getLogger(__name__)

USER_AGENT = "ShipArchiveLite/0.10 (course project; https://github.com/kiwijos/basic-archive)"
SOURCE_SYSTEM = "wikimedia-commons"
BASIS = "The author, Fredrik Henrik af Chapman, died in 1808, so the rights have long since run out (Commons template PD-old-100)."
CHECKED = "2026-10-24"  # when the Commons file pages were read and these checksums recorded


class PlateUnavailable(Exception):
    """A plate could not be fetched (no network, or Commons did not have it)."""


class PlateIntegrityError(Exception):
    """What was fetched is not the file that was checked."""


@dataclass(frozen=True)
class Plate:
    title: str  # the Commons file name
    url: str
    page: str
    author: str
    year: int
    licence: str
    basis: str
    sha1: str  # as reported by Commons
    sha256: str
    bytes: int
    width: int
    height: int
    mime: str = "image/jpeg"


def _plate(title: str, path: str, sha1: str, sha256: str, size: int, width: int, height: int) -> Plate:
    name = title.replace(" ", "_")
    return Plate(
        title=f"File:{title}",
        url=f"https://upload.wikimedia.org/wikipedia/commons/{path}",
        page=f"https://commons.wikimedia.org/wiki/File:{name}",
        author="Fredrik Henrik af Chapman (1721–1808)",
        year=1768,
        licence="Public domain",
        basis=BASIS,
        sha1=sha1,
        sha256=sha256,
        bytes=size,
        width=width,
        height=height,
    )


PLATES = {
    "hagboat-viii": _plate("Chapman Hagboat VIII.jpg", "3/36/Chapman_Hagboat_VIII.jpg",
                           "e67d11b6b308c475bcbb16c26f93004fa42eb616", "4e7a915faac14845af6a7dd1ef06ee5f5d78a02661bf176e072c0dfa5dfa5f20", 8300191, 8928, 6383),
    "hagboat-ix": _plate("Chapman Hagboat IX.jpg", "3/3f/Chapman_Hagboat_IX.jpg",
                         "2894dcdefa41d434326540edc0b722adf75d331c", "da4733029cb80d105fa539cb59f48b7ff67336c3bc1c883fc2b1dff89b77bf18", 9956643, 9000, 6503),
    "plate-40": _plate("Plate 40 Architectura navalis mercatoria.JPG", "7/7c/Plate_40_Architectura_navalis_mercatoria.JPG",
                       "dcc2568c2d9d4d07e16294e89fc7bdd961354861", "20316fa984e21e7713b327d83ec4961d535c68451e8ccd50b0e3304a8fb3245a", 10569709, 8880, 6574),
    "schooner": _plate("Schooner 1700s Chapman.JPG", "c/cd/Schooner_1700s_Chapman.JPG",
                       "b7df45055782b52fe6b90001d0e8e7df79c86f3f", "70620706e5c9423eacfd36994051f93e746b27da43d03823a93207a567897c1f", 748290, 2605, 1901),
}


@dataclass(frozen=True)
class PlateDocument:
    key: str
    title: str
    plates: tuple[str, ...]  # keys of PLATES, one per sheet, in page order
    date: Period
    note: str  # what the Document is, before the provenance

    @property
    def description(self) -> str:
        return self.describe(PLATES)

    def describe(self, plates: dict[str, Plate]) -> str:
        sources = "; ".join(f"{plates[k].title} ({plates[k].page})" for k in self.plates)
        first = plates[self.plates[0]]
        return (
            f"{self.note} Drawing by {first.author}, from Architectura Navalis Mercatoria, Stockholm, {first.year}. "
            f"Source: Wikimedia Commons: {sources}. Public domain: {first.basis} "
            f"Fetched and checked against a recorded SHA-256 ({CHECKED}). "
            "Not part of the fictional fleet: these are real eighteenth-century plans."
        )


PLATE_DOCUMENTS = (
    PlateDocument(
        key="plate-hagboat",
        title="Hagbåt: planscherna VIII och IX (Chapman, 1768)",
        plates=("hagboat-viii", "hagboat-ix"),
        date=Period("1768", "1768-01-01", "1768-12-31"),
        note="Two sheets of design drawings of a hagboat, a type of small naval vessel.",
    ),
    PlateDocument(
        key="plate-40",
        title="Plansch 40 ur Architectura Navalis Mercatoria (Chapman, 1768)",
        plates=("plate-40",),
        date=Period("1768", "1768-01-01", "1768-12-31"),
        note="Plate 40 of the collection of merchant ship designs.",
    ),
    PlateDocument(
        key="plate-schooner",
        title="Liten skonare (Chapman, 1768)",
        plates=("schooner",),
        date=Period("1768", "1768-01-01", "1768-12-31"),
        note="A small schooner, as drawn for the collection.",
    ),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_plate(plate: Plate, cache: Path, *, timeout: float = 120.0) -> Path:
    """The plate as a local file whose SHA-256 is the one recorded, fetched only if it is not already kept.

    A kept file that no longer matches is fetched again. A download that does not match is refused and
    nothing is kept, so a changed or replaced file can never reach the archive.
    """
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / f"{plate.sha256}.jpg"
    if target.exists():
        if _sha256(target) == plate.sha256:
            return target
        logger.warning("%s in the cache is damaged, fetching it again", target.name)
        target.unlink()
    partial = target.with_suffix(".part")
    try:
        with httpx.stream("GET", plate.url, headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=True) as response:
            if response.status_code != 200:
                raise PlateUnavailable(f"{plate.title}: the server answered {response.status_code}")
            with partial.open("wb") as file:
                for block in response.iter_bytes(1 << 20):
                    file.write(block)
    except httpx.HTTPError as error:
        partial.unlink(missing_ok=True)
        raise PlateUnavailable(f"{plate.title}: {error}") from error
    if _sha256(partial) != plate.sha256:
        partial.unlink()
        raise PlateIntegrityError(f"{plate.title}: what was fetched is not the file whose checksum is recorded")
    partial.rename(target)
    return target
