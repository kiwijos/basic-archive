import pytest

from archive_seed.documents import DOCUMENTS
from archive_seed.fleet import SOURCE_SYSTEM
from archive_seed.loader import SeedError, Seeder

API = "/api/catalog"
BY_KEY = {d.key: d for d in DOCUMENTS}


def damage(text: str, errors: int = 20) -> str:
    """The text with its first letters replaced by '#', so it is wrong in exactly that many places."""
    out, left = [], errors
    for char in text:
        if left and char.isalpha():
            out.append("#")
            left -= 1
        else:
            out.append(char)
    return "".join(out)


def length(text: str) -> int:
    return len(" ".join(text.split()))


def documents(archive):
    found = archive.get(f"{API}/documents", params={"source_system": SOURCE_SYSTEM}).json()
    return {d["source_id"]: d for d in found}


def run(archive, **options):
    seeder = Seeder(archive, ocr_timeout=30, poll=0.05, **options)
    seeder.seed_fleet()
    seeder.seed_documents()
    seeder.seed_readings()
    return seeder


def test_each_page_is_measured_against_the_text_it_really_has_using_the_machine_reading(archive, worker):
    worker.distort = lambda text, key, page: damage(text)

    report = run(archive).report

    assert len(report.pages) == sum(len(d.pages) for d in DOCUMENTS)
    for result in report.pages:
        reference = BY_KEY[result.document].pages[result.page - 1]
        assert result.quality == BY_KEY[result.document].quality
        assert result.accuracy == pytest.approx(1 - 20 / length(reference))
        assert result.characters == length(reference)


def test_accuracy_is_reported_per_quality_and_overall_weighted_by_how_much_text_there_is(archive, worker):
    worker.distort = lambda text, key, page: damage(text) if BY_KEY[key].quality == "faded" else text

    report = run(archive).report

    faded = [d for d in DOCUMENTS if d.quality == "faded"]
    faded_pages = [text for d in faded for text in d.pages]
    assert report.by_quality()["clean"] == 1.0
    assert report.by_quality()["skewed"] == 1.0
    assert report.by_quality()["faded"] == pytest.approx(1 - 20 * len(faded_pages) / sum(length(t) for t in faded_pages))
    everything = [text for d in DOCUMENTS for text in d.pages]
    assert report.overall() == pytest.approx(1 - 20 * len(faded_pages) / sum(length(t) for t in everything))
    assert set(report.by_quality()) == {"clean", "faded", "skewed", "speckled"}


def test_the_documents_are_verified_machine_only_or_partly_as_each_one_is_meant_to_be(archive, worker):
    run(archive)

    made = documents(archive)
    for seed in DOCUMENTS:
        document = made[seed.key]
        verified = {i["page_no"]: i["verified"] for i in document["images"]}
        if seed.state == "verified":
            assert all(verified.values()) and document["verified"], seed.key
        elif seed.state == "machine":
            assert not any(verified.values()) and not document["verified"], seed.key
        else:
            assert verified[1] and not verified[2] and not document["verified"], seed.key
    assert {d.state for d in DOCUMENTS} == {"verified", "machine", "partial"}


def test_a_verified_page_holds_the_true_text_and_a_machine_only_page_keeps_the_readers_own(archive, worker):
    worker.distort = lambda text, key, page: damage(text)

    run(archive)

    made = documents(archive)
    verified = next(d for d in DOCUMENTS if d.state == "verified")
    machine = next(d for d in DOCUMENTS if d.state == "machine")
    first = {i["page_no"]: i for i in made[verified.key]["images"]}[1]
    assert first["text_source"] == "human" and first["current_text"] == verified.pages[0]
    only = {i["page_no"]: i for i in made[machine.key]["images"]}[1]
    assert only["text_source"] == "machine" and only["current_text"] == damage(machine.pages[0])


def test_running_again_gives_the_same_accuracy_even_though_the_pages_now_have_a_perfect_human_text(archive, worker):
    worker.distort = lambda text, key, page: damage(text)
    first = run(archive).report

    again = Seeder(archive, ocr_timeout=30, poll=0.05)
    again.seed_fleet()
    again.seed_documents()
    again.seed_readings()

    assert [(p.document, p.page, p.accuracy) for p in again.report.pages] == [(p.document, p.page, p.accuracy) for p in first.pages]
    assert again.report.created["verified pages"] == 0
    assert len(worker.reads) == sum(len(d.pages) for d in DOCUMENTS)


def test_a_page_the_ocr_failed_on_is_reported_as_failed_not_as_zero_and_does_not_stop_the_rest(archive, worker):
    worker.fail = lambda key, page: (key, page) == ("doc-kontrakt-1889", 1)

    report = run(archive).report

    failed = [p for p in report.pages if p.accuracy is None]
    assert [(p.document, p.page) for p in failed] == [("doc-kontrakt-1889", 1)]
    assert report.by_quality()["clean"] == 1.0
    assert report.overall() == 1.0
    assert documents(archive)["doc-kontrakt-1889"]["verified"]  # a person's reading settles it all the same


def test_without_a_reader_the_wait_ends_with_an_error_that_names_what_was_left(archive):
    seeder = Seeder(archive, ocr_timeout=0.5, poll=0.05)
    seeder.seed_fleet()
    seeder.seed_documents()

    with pytest.raises(SeedError, match=r"still waiting for OCR.*doc-kontrakt-1889"):
        seeder.seed_readings()
    assert not any(i["verified"] for d in documents(archive).values() for i in d["images"])  # nothing verified on a guess
