"""A fictional fleet: invented firms and ships with a life, for the demo.

Nothing here is real. The firms, the ships and what happened to them were made up for this archive, and
every name and relation says so. The story: a barque is built in 1889, sold in 1903, renamed twice, and in 1933 its
hull is rebuilt into a motor vessel, which is a new Ship linked back to the old one.
"""

from dataclasses import dataclass, field

SOURCE_SYSTEM = "seed"
SYNTHETIC = "Synthetic demo data: invented for this archive"


@dataclass(frozen=True)
class Period:
    text: str | None = None
    start: str | None = None
    end: str | None = None


@dataclass(frozen=True)
class OrganisationSeed:
    key: str
    name: str
    kind: str
    place: str


@dataclass(frozen=True)
class RelationSeed:
    predicate: str  # built_by, owned_by, operated_by or rebuilt_from
    other: str  # the key of the Subject at the other end
    period: Period
    place: str | None = None


@dataclass(frozen=True)
class RenameSeed:
    name: str
    starts: str  # the day the Ship took this name


@dataclass(frozen=True)
class ShipSeed:
    key: str
    first_name: str
    ship_type: str
    tonnage: float
    launched: Period
    fate: str | None = None
    fate_date: Period | None = None
    renames: tuple[RenameSeed, ...] = ()
    relations: tuple[RelationSeed, ...] = field(default_factory=tuple)


ORGANISATIONS = (
    OrganisationSeed("org-alvsborg", "Älvsborgs Skeppsvarv", "shipyard", "Göteborg"),
    OrganisationSeed("org-nordsjo", "Rederi AB Nordsjö", "shipping company", "Göteborg"),
    OrganisationSeed("org-sund", "Rederi AB Sund", "shipping company", "Stockholm"),
)

SHIPS = (
    ShipSeed(
        key="ship-nordstjarnan",
        first_name="Nordstjärnan",
        ship_type="barque",
        tonnage=871,
        launched=Period("mars 1889", "1889-03-01", "1889-03-31"),
        fate="Hull rebuilt as the motor vessel Älvdrottningen",
        fate_date=Period("1933–34", "1933-09-05", "1934-06-15"),
        renames=(RenameSeed("Sofia", "1903-04-15"), RenameSeed("Havsörnen", "1921-03-01")),
        relations=(
            RelationSeed("built_by", "org-alvsborg", Period("1889", "1889-01-14", "1889-05-01"), "Göteborg"),
            RelationSeed("owned_by", "org-nordsjo", Period("1889–1903", "1889-05-01", "1903-04-15")),
            RelationSeed("owned_by", "org-sund", Period("från 1903", "1903-04-15", None)),
        ),
    ),
    ShipSeed(
        key="ship-linnea",
        first_name="Linnea",
        ship_type="schooner",
        tonnage=143,
        launched=Period("1901", "1901-06-01", "1901-06-30"),
        relations=(
            RelationSeed("built_by", "org-alvsborg", Period("1901", "1900-11-03", "1901-08-01"), "Göteborg"),
            RelationSeed("owned_by", "org-nordsjo", Period("från 1901", "1901-08-01", None)),
        ),
    ),
    ShipSeed(
        key="ship-svalan",
        first_name="Svalan",
        ship_type="steamer",
        tonnage=96,
        launched=Period("1912", "1912-04-01", "1912-04-30"),
        relations=(
            RelationSeed("built_by", "org-alvsborg", Period("1912", "1911-10-01", "1912-06-01"), "Göteborg"),
            RelationSeed("owned_by", "org-sund", Period("från 1912", "1912-06-01", None)),
        ),
    ),
    ShipSeed(
        key="ship-alvdrottningen",
        first_name="Älvdrottningen",
        ship_type="motor vessel",
        tonnage=640,
        launched=Period("juni 1934", "1934-06-01", "1934-06-30"),
        relations=(
            RelationSeed("rebuilt_from", "ship-nordstjarnan", Period("1933–34", "1933-09-05", "1934-06-15"), "Göteborg"),
            RelationSeed("built_by", "org-alvsborg", Period("1933–34", "1933-09-05", "1934-06-15"), "Göteborg"),
            RelationSeed("owned_by", "org-nordsjo", Period("från 1934", "1934-07-01", None)),
        ),
    ),
)
