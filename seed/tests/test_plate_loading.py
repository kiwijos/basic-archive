import hashlib

import pytest
from conftest import FILES

from archive_seed.loader import Seeder
from archive_seed.plates import SOURCE_SYSTEM, Plate, PlateIntegrityError

API = "/api/catalog"
NOTE = "[Ritning utan löpande text]"


def seeder(archive, tmp_path, fixture_plates, **options):
    _, plates, documents = fixture_plates
    return Seeder(archive, cache_dir=tmp_path / "cache", plates=plates, plate_documents=documents, ocr_timeout=30, poll=0.05, **options)


def stored(archive):
    found = archive.get(f"{API}/documents", params={"source_system": SOURCE_SYSTEM}).json()
    return {d["source_id"]: d for d in found}


def test_each_plate_document_is_uploaded_as_public_domain_with_every_sheet_and_where_it_came_from(archive, worker, tmp_path, fixture_plates):
    seeder(archive, tmp_path, fixture_plates).seed_plates()

    made = stored(archive)
    assert sorted(made) == ["plate-one", "plate-two"]
    two = made["plate-two"]
    assert two["title"] == "Two sheets" and two["document_type"] == "drawing"
    assert [i["page_no"] for i in two["images"]] == [1, 2]
    assert {i["rights"] for d in made.values() for i in d["images"]} == {"PDM"}
    assert "Wikimedia Commons" in two["description"] and "https://commons.wikimedia.org/wiki/File:Plate_a.jpg" in two["description"]
    for document, key in (("plate-two", "a"), ("plate-two", "b"), ("plate-one", "c")):
        image = next(i for i in made[document]["images"] if i["sha256"] == hashlib.sha256(FILES[key]).hexdigest())
        assert archive.get(f"{API}/images/{image['id']}/content").content == FILES[key]


def test_a_drawing_has_no_running_text_so_a_person_notes_that_after_the_machine_has_had_its_turn(archive, worker, tmp_path, fixture_plates):
    seeder(archive, tmp_path, fixture_plates).seed_plates()

    for document in stored(archive).values():
        assert document["verified"]
        for image in document["images"]:
            sources = [t["source"] for t in archive.get(f"{API}/images/{image['id']}/transcriptions").json()]
            assert sources == ["human", "machine"]  # newest first: the OCR was recorded before the note replaced it
            assert image["current_text"] == NOTE and image["text_source"] == "human"


def test_plates_are_not_measured_because_there_is_no_text_to_measure_against(archive, worker, tmp_path, fixture_plates):
    plates = seeder(archive, tmp_path, fixture_plates)
    plates.seed_plates()

    assert plates.report.pages == []


def test_when_commons_cannot_be_reached_the_plates_are_skipped_out_loud_and_nothing_half_made_is_left(archive, worker, tmp_path, served, fixture_plates):
    server, plates, documents = fixture_plates
    broken = {**plates, "b": Plate(**{**plates["b"].__dict__, "url": f"{server.url}/missing.jpg"})}  # the second sheet is missing
    seed = Seeder(archive, cache_dir=tmp_path / "cache", plates=broken, plate_documents=documents, ocr_timeout=30, poll=0.05)

    seed.seed_plates()

    assert sorted(stored(archive)) == ["plate-one"]  # the Document that needs the missing sheet is not started at all
    assert len(seed.report.skipped) == 1 and "plate-two" in seed.report.skipped[0] and "Plate b.jpg" in seed.report.skipped[0]


def test_a_file_that_is_not_the_one_that_was_checked_stops_the_seed_and_uploads_nothing(archive, worker, tmp_path, served, fixture_plates):
    server, plates, documents = fixture_plates
    swapped = {**plates, "c": Plate(**{**plates["c"].__dict__, "sha256": "0" * 64})}
    seed = Seeder(archive, cache_dir=tmp_path / "cache", plates=swapped, plate_documents=documents, ocr_timeout=30, poll=0.05)

    with pytest.raises(PlateIntegrityError):
        seed.seed_plates()

    assert "plate-one" not in stored(archive)


def test_running_again_makes_nothing_new_and_needs_no_network_when_the_plates_are_already_there(archive, worker, tmp_path, fixture_plates):
    server, _, _ = fixture_plates
    seeder(archive, tmp_path, fixture_plates).seed_plates()
    before = {k: [i["id"] for i in d["images"]] for k, d in stored(archive).items()}
    server.http.shutdown()  # the network is gone, and so is the cache
    again = Seeder(archive, cache_dir=tmp_path / "elsewhere", plates=fixture_plates[1], plate_documents=fixture_plates[2], ocr_timeout=30, poll=0.05)

    again.seed_plates()

    assert {k: [i["id"] for i in d["images"]] for k, d in stored(archive).items()} == before
    assert again.report.skipped == [] and again.report.created["plate documents"] == 0
    assert again.report.found["plate documents"] == 2 and again.report.created["verified pages"] == 0
