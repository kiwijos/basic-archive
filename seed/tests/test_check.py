import httpx

from archive_seed.check import Check
from archive_seed.documents import DOCUMENTS
from archive_seed.loader import Seeder

API = "/api/catalog"


def nowhere() -> httpx.Client:
    """A public side that answers nothing is enough for the checks that only read the catalog."""
    return httpx.Client(base_url="http://127.0.0.1:1", timeout=1)


def outcome(findings, fragment):
    return next(f.outcome for f in findings if fragment in f.name)


def test_a_refused_token_is_a_failed_check_with_the_reason_not_a_traceback(archive):
    stranger = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(401, json={"detail": "A valid staff token is required"})), base_url="http://archive")

    check = Check(stranger, nowhere(), index_wait=0)
    findings = check.run()

    assert check.failed
    assert len(findings) == 1 and findings[0].outcome == "FAIL" and "401" in findings[0].detail


def test_the_ocr_accuracy_check_fails_when_any_page_could_not_be_read(archive, worker):
    worker.fail = lambda key, page: (key, page) == ("doc-kontrakt-1889", 1)
    seeder = Seeder(archive, ocr_timeout=30, poll=0.05)
    seeder.seed_fleet()
    seeder.seed_documents()
    seeder.seed_readings()

    check = Check(archive, nowhere(), index_wait=0)
    check._accuracy()

    assert outcome(check.findings, "OCR accuracy") == "FAIL"
    pages = sum(len(d.pages) for d in DOCUMENTS)
    assert f"{pages - 1} of {pages} pages" in check.findings[0].detail


def test_the_ocr_accuracy_check_passes_when_every_page_was_read(archive, worker):
    seeder = Seeder(archive, ocr_timeout=30, poll=0.05)
    seeder.seed_fleet()
    seeder.seed_documents()
    seeder.seed_readings()

    check = Check(archive, nowhere(), index_wait=0)
    check._accuracy()

    assert outcome(check.findings, "OCR accuracy") == "ok"
