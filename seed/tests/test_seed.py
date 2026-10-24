import pytest

from archive_seed.documents import DOCUMENTS
from archive_seed.fleet import ORGANISATIONS, SHIPS, SOURCE_SYSTEM
from archive_seed.loader import PageResult, Report, SeedError, Seeder

API = "/api/catalog"


class Crash(Exception):
    pass


class Crashing:
    """The archive's API, until the nth change goes through, and then the seed process dies: either just before
    the change is made, or just after it, with the answer lost on the way back."""

    def __init__(self, inner, at: int, after: bool):
        self.inner, self.at, self.after, self.changes = inner, at, after, 0

    def request(self, method, url, **kwargs):
        if method == "GET":
            return self.inner.request(method, url, **kwargs)
        self.changes += 1
        if self.changes == self.at and not self.after:
            raise Crash
        response = self.inner.request(method, url, **kwargs)
        if self.changes == self.at and self.after:
            raise Crash
        return response


def made(archive) -> dict:
    """Everything the seed makes, in a form that two runs can be compared by."""
    get = lambda path, **params: archive.get(f"{API}{path}", params=params).json()  # noqa: E731
    ships = {s["source_id"]: s for s in get("/ships", source_system=SOURCE_SYSTEM)}
    firms = {o["source_id"]: o for o in get("/organisations", source_system=SOURCE_SYSTEM)}
    documents = {d["source_id"]: d for d in get("/documents", source_system=SOURCE_SYSTEM)}
    return {
        "ships": sorted(ships),
        "firms": sorted(firms),
        "names": {k: [n["name"] for n in get(f"/subjects/{s['id']}/names")] for k, s in ships.items()},
        "relations": {
            k: sorted((r["predicate"], r["from_subject_id"], r["to_subject_id"]) for r in get(f"/subjects/{s['id']}/relations"))
            for k, s in ships.items()
        },
        "pages": {k: len(d["images"]) for k, d in documents.items()},
        "verified": {k: d["verified_images"] for k, d in documents.items()},
        "links": {k: sorted((s["subject_id"], s["role"]) for s in d["subjects"]) for k, d in documents.items()},
    }


def test_the_whole_seed_makes_the_fleet_the_documents_and_the_plates_and_reports_what_it_did(archive, worker, tmp_path, fixture_plates):
    _, plates, plate_documents = fixture_plates
    seeder = Seeder(archive, cache_dir=tmp_path, plates=plates, plate_documents=plate_documents, ocr_timeout=60, poll=0.05)

    report = seeder.seed()

    assert report.created["ships"] == len(SHIPS) and report.created["organisations"] == len(ORGANISATIONS)
    assert report.created["documents"] == len(DOCUMENTS) and report.created["plate documents"] == 2
    assert len(report.pages) == sum(len(d.pages) for d in DOCUMENTS)
    state = made(archive)
    assert state["ships"] == sorted(s.key for s in SHIPS)
    assert {k: v for k, v in state["pages"].items()} == {d.key: len(d.pages) for d in DOCUMENTS}


def test_the_seed_can_leave_the_plates_out(archive, worker, tmp_path):
    seeder = Seeder(archive, cache_dir=tmp_path, with_plates=False, ocr_timeout=60, poll=0.05)

    seeder.seed()

    assert archive.get(f"{API}/documents", params={"source_system": "wikimedia-commons"}).json() == []


def test_a_second_run_changes_nothing_at_all(archive, worker, tmp_path, fixture_plates):
    _, plates, plate_documents = fixture_plates
    options = dict(cache_dir=tmp_path, plates=plates, plate_documents=plate_documents, ocr_timeout=60, poll=0.05)
    Seeder(archive, **options).seed()
    before = made(archive)

    again = Seeder(archive, **options).seed()

    assert made(archive) == before
    assert sum(again.created.values()) == 0, dict(again.created)


@pytest.mark.parametrize("at", [2, 9, 21, 40])
@pytest.mark.parametrize("after", [False, True], ids=["dies before the change", "dies after the change"])
def test_a_run_that_dies_anywhere_is_finished_by_the_next_with_exactly_what_one_clean_run_makes(archive, worker, tmp_path, at, after):
    options = dict(cache_dir=tmp_path, with_plates=False, ocr_timeout=60, poll=0.05)
    with pytest.raises(Crash):
        Seeder(Crashing(archive, at, after), **options).seed()

    Seeder(archive, **options).seed()
    recovered = made(archive)

    assert recovered["ships"] == sorted(s.key for s in SHIPS)
    assert recovered["pages"] == {d.key: len(d.pages) for d in DOCUMENTS}
    assert recovered["names"]["ship-nordstjarnan"] == ["Nordstjärnan", "Sofia", "Havsörnen"]
    for ship in SHIPS:
        assert len(recovered["relations"][ship.key]) == len(set(recovered["relations"][ship.key])), "a relation was made twice"
    expected = {d.key: len(d.pages) if d.state == "verified" else 1 if d.state == "partial" else 0 for d in DOCUMENTS}
    assert recovered["verified"] == expected
    assert all(len(set(links)) == len(links) for links in recovered["links"].values())
    assert len(Seeder(archive, **options).seed().pages) == sum(len(d.pages) for d in DOCUMENTS)


def test_a_ship_that_was_deleted_keeps_its_key_so_the_seed_stops_and_says_why_instead_of_making_a_twin(archive, worker, tmp_path):
    Seeder(archive, cache_dir=tmp_path, with_plates=False, ocr_timeout=60, poll=0.05).seed_fleet()
    ship = archive.get(f"{API}/ships", params={"source_system": SOURCE_SYSTEM, "source_id": "ship-linnea"}).json()[0]
    assert archive.delete(f"{API}/ships/{ship['id']}").status_code == 204

    with pytest.raises(SeedError, match=r"ship-linnea.*deleted"):
        Seeder(archive, cache_dir=tmp_path).seed_fleet()


def test_the_accuracy_table_says_how_many_pages_how_well_and_which_ones_failed():
    report = Report(
        pages=[
            PageResult("a", 1, "clean", 1.0, 100),
            PageResult("b", 1, "clean", 0.9, 100),
            PageResult("c", 1, "faded", 0.5, 200),
            PageResult("d", 1, "faded", None, 300),
        ]
    )

    lines = report.table().splitlines()

    assert any(line.split() == ["clean", "2", "pages", "95.0", "%"] for line in lines), lines
    assert any(line.split() == ["faded", "1", "page", "50.0", "%"] for line in lines), lines
    assert any(line.split()[:1] == ["all"] and "3 pages" in line and "(1 OCR failed)" in line and "72.5 %" in line for line in lines), lines


class Raced:
    """Another seed run gets there first: the first time this path is posted to, the same request has just been made."""

    def __init__(self, inner, path: str):
        self.inner, self.path, self.raced = inner, path, False

    def request(self, method, url, **kwargs):
        if method == "POST" and url == f"{API}{self.path}" and not self.raced:
            self.raced = True
            assert self.inner.request(method, url, **kwargs).status_code == 201
        return self.inner.request(method, url, **kwargs)


@pytest.mark.parametrize("path", ["/ships", "/organisations", "/documents"])
def test_when_another_run_makes_a_record_first_this_run_uses_it_instead_of_failing_or_duplicating(archive, worker, tmp_path, path):
    racing = Raced(archive, path)
    seeder = Seeder(racing, cache_dir=tmp_path, with_plates=False, ocr_timeout=60, poll=0.05)

    seeder.seed()

    assert racing.raced
    state = made(archive)
    assert state["ships"] == sorted(s.key for s in SHIPS) and state["firms"] == sorted(o.key for o in ORGANISATIONS)
    assert state["pages"] == {d.key: len(d.pages) for d in DOCUMENTS}
    assert seeder.report.found[path.strip("/")] >= 1
