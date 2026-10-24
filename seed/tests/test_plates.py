import hashlib

import pytest

from archive_seed.plates import PLATE_DOCUMENTS, PLATES, Plate, PlateIntegrityError, PlateUnavailable, fetch_plate

ALLOWED_LICENCES = {"public domain"}


# ---- the manifest: what makes a plate safe to publish ----------------------------------------------------------------


def test_every_plate_records_who_made_it_where_it_is_from_and_why_it_is_free_to_use():
    assert PLATES
    for plate in PLATES.values():
        assert plate.url.startswith("https://upload.wikimedia.org/"), plate.title
        assert plate.page.startswith("https://commons.wikimedia.org/wiki/File:"), plate.title
        assert plate.licence.lower() in ALLOWED_LICENCES, plate.title
        assert "1808" in plate.basis or "100" in plate.basis, f"{plate.title}: say why the rights have run out"
        assert plate.author and plate.year == 1768
        assert len(plate.sha256) == 64 and len(plate.sha1) == 40
        assert plate.bytes > 100_000 and plate.width * plate.height > 3_000_000, "a plate worth zooming into"


def test_every_plate_that_a_document_uses_is_in_the_manifest_and_every_plate_is_used():
    used = [key for doc in PLATE_DOCUMENTS for key in doc.plates]

    assert set(used) == set(PLATES)
    assert len(used) == len(set(used)), "a plate would be uploaded twice"
    assert any(len(doc.plates) > 1 for doc in PLATE_DOCUMENTS), "the demo shows a Document with more than one sheet"


def test_a_plate_document_says_where_it_came_from_in_words_a_visitor_can_read():
    for doc in PLATE_DOCUMENTS:
        text = doc.description
        assert "Wikimedia Commons" in text and "Public domain" in text
        for key in doc.plates:
            plate = PLATES[key]
            assert plate.page in text and plate.author in text


# ---- fetching: verified, cached, and honest about failing -----------------------------------------------------------


def plate_for(server, body: bytes, path="/plate.jpg") -> Plate:
    real = next(iter(PLATES.values()))
    return Plate(**{**real.__dict__, "url": server.url + path, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)})


def test_a_plate_is_downloaded_once_checked_and_kept_so_the_next_run_needs_no_network(served, tmp_path):
    body = b"\xff\xd8\xff pretend this is a very large drawing " * 50
    server = served({"/plate.jpg": body})
    plate = plate_for(server, body)

    first = fetch_plate(plate, tmp_path)
    second = fetch_plate(plate, tmp_path)

    assert first == second and first.read_bytes() == body
    assert len(server.requests) == 1
    assert "ShipArchiveLite" in server.requests[0] and "github.com/kiwijos/basic-archive" in server.requests[0]


def test_a_download_that_is_not_the_file_that_was_checked_is_refused_and_not_kept(served, tmp_path):
    server = served({"/plate.jpg": b"somebody replaced this file"})
    plate = plate_for(server, b"the file that was checked")

    with pytest.raises(PlateIntegrityError):
        fetch_plate(plate, tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_a_kept_file_that_was_damaged_is_fetched_again(served, tmp_path):
    body = b"the real drawing " * 100
    server = served({"/plate.jpg": body})
    plate = plate_for(server, body)
    path = fetch_plate(plate, tmp_path)
    path.write_bytes(b"truncated")

    again = fetch_plate(plate, tmp_path)

    assert again.read_bytes() == body and len(server.requests) == 2


def test_a_server_that_is_down_or_missing_the_file_is_unavailable_not_a_crash(served, tmp_path):
    server = served({})
    with pytest.raises(PlateUnavailable):
        fetch_plate(plate_for(server, b"x"), tmp_path)
    with pytest.raises(PlateUnavailable):
        fetch_plate(Plate(**{**next(iter(PLATES.values())).__dict__, "url": "http://127.0.0.1:1/x.jpg"}), tmp_path)
