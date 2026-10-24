import pytest

from archive_seed.documents import DOCUMENTS
from archive_seed.fleet import SOURCE_SYSTEM
from archive_seed.loader import Seeder
from archive_seed.render import mime_of, render_page

API = "/api/catalog"


def seeded(archive):
    found = archive.get(f"{API}/documents", params={"source_system": SOURCE_SYSTEM}).json()
    return {d["source_id"]: d for d in found}


@pytest.fixture
def loaded(archive):
    seeder = Seeder(archive)
    seeder.seed_fleet()
    seeder.seed_documents()
    return seeder


def test_every_document_is_uploaded_with_what_the_ticket_says_it_is_and_free_for_anyone_to_use(archive, loaded):
    documents = seeded(archive)

    assert sorted(documents) == sorted(d.key for d in DOCUMENTS)
    for seed in DOCUMENTS:
        made = documents[seed.key]
        assert made["title"] == seed.title and made["document_type"] == seed.kind
        assert made["date"]["date_text"] == seed.date.text
        assert made["image_count"] == len(seed.pages)
        assert {image["rights"] for image in made["images"]} == {"CC0"}
        assert "Synthetic demo document" in made["description"] and "fictional" in made["description"]
        assert seed.quality in made["description"]


def test_each_page_is_the_scan_that_the_renderer_makes_so_the_text_on_it_is_known(archive, loaded):
    documents = seeded(archive)

    for seed in DOCUMENTS:
        images = sorted(documents[seed.key]["images"], key=lambda i: i["page_no"])
        assert [i["page_no"] for i in images] == list(range(1, len(seed.pages) + 1))
        for image, text in zip(images, seed.pages):
            assert image["mime"] == mime_of(seed.format)
            stored = archive.get(f"{API}/images/{image['id']}/content").content
            assert stored == render_page(text, font=seed.font, quality=seed.quality, fmt=seed.format, key=f"{seed.key}:{image['page_no']}")


def test_documents_are_linked_to_the_ships_and_firms_they_are_about(archive, loaded):
    documents = seeded(archive)

    contract = documents["doc-kontrakt-1889"]
    assert sorted((s["kind"], s["name"], s["role"]) for s in contract["subjects"]) == sorted(
        [("ship", "Havsörnen", "about"), ("organisation", "Älvsborgs Skeppsvarv", "party"), ("organisation", "Rederi AB Nordsjö", "party")]
    )
    rebuild = documents["doc-ombyggnad-1933"]
    assert {s["name"] for s in rebuild["subjects"] if s["kind"] == "ship"} == {"Havsörnen", "Älvdrottningen"}


def test_loading_the_documents_again_makes_none_and_the_report_says_so(archive, loaded):
    first = loaded.report.created["documents"]
    again = Seeder(archive)
    again.seed_fleet()
    again.seed_documents()

    pages = sum(len(d.pages) for d in DOCUMENTS)
    assert first == len(DOCUMENTS)
    assert loaded.report.created["pages"] == pages and loaded.report.found["pages"] == 0  # a page is made or found, never both
    assert again.report.found["pages"] == pages
    assert again.report.created["documents"] == 0 and again.report.created["pages"] == 0
    assert again.report.found["documents"] == len(DOCUMENTS)
    assert len(seeded(archive)) == len(DOCUMENTS)
    assert sum(len(d["images"]) for d in seeded(archive).values()) == sum(len(d.pages) for d in DOCUMENTS)


def test_a_ship_that_the_fleet_does_not_have_is_a_clear_error_not_a_quiet_gap(archive):
    seeder = Seeder(archive)

    from archive_seed.loader import SeedError

    with pytest.raises(SeedError, match="ship-nordstjarnan"):
        seeder.seed_documents()  # the fleet was never loaded
