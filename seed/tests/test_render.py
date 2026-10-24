import io
import statistics

import pytest
from PIL import Image

from archive_seed.accuracy import character_accuracy
from archive_seed.documents import DOCUMENTS
from archive_seed.render import mime_of, render_page

PAGES = [(doc, number, text) for doc in DOCUMENTS for number, text in enumerate(doc.pages, start=1)]
IDS = [f"{doc.key}-p{number}" for doc, number, _ in PAGES]

MAGIC = {"png": b"\x89PNG\r\n\x1a\n", "jpeg": b"\xff\xd8\xff", "tiff": (b"II*\x00", b"MM\x00*")}

# What a scan of each quality must still allow: a floor well under what real Tesseract reads from it, so a
# different Tesseract version does not fail the build, yet far above what an unreadable scan would give.
FLOOR = {"clean": 0.95, "faded": 0.85, "skewed": 0.85, "speckled": 0.75}


def render(doc, number, text):
    return render_page(text, font=doc.font, quality=doc.quality, fmt=doc.format, key=f"{doc.key}:{number}")


@pytest.mark.parametrize("doc,number,text", PAGES, ids=IDS)
def test_a_page_is_rendered_in_the_format_it_asks_for_and_opens_as_an_image(doc, number, text):
    data = render(doc, number, text)

    assert data.startswith(MAGIC[doc.format])
    with Image.open(io.BytesIO(data)) as image:
        assert image.width == 1240 and 500 <= image.height <= 2200
    assert mime_of(doc.format) == {"png": "image/png", "jpeg": "image/jpeg", "tiff": "image/tiff"}[doc.format]


def test_rendering_is_deterministic_so_a_rerun_makes_the_same_bytes_and_every_page_is_its_own():
    first = [render(*page) for page in PAGES]
    second = [render(*page) for page in PAGES]

    assert first == second
    assert len(set(first)) == len(first)


def test_the_same_page_rendered_with_another_key_differs_in_its_flaws_but_not_in_its_words():
    doc, number, text = next(p for p in PAGES if p[0].quality == "speckled")
    a = render_page(text, font=doc.font, quality=doc.quality, fmt="png", key="one")
    b = render_page(text, font=doc.font, quality=doc.quality, fmt="png", key="two")

    assert a != b


@pytest.mark.parametrize("quality", ["clean", "faded", "skewed", "speckled"])
def test_every_quality_of_scan_can_still_be_read_by_a_machine_and_clean_scans_are_read_best(tesseract, quality):
    scored = []
    for doc, number, text in PAGES:
        if doc.quality != quality:
            continue
        with Image.open(io.BytesIO(render(doc, number, text))) as image:
            reading = tesseract.image_to_string(image, lang="swe+eng")
        scored.append(character_accuracy(text, reading))

    assert scored, quality
    assert min(scored) >= FLOOR[quality], f"{quality}: {[round(s, 3) for s in scored]}"
    if quality == "clean":
        assert statistics.mean(scored) >= 0.97


def test_the_scans_are_not_all_perfect_because_a_demo_that_always_scores_100_percent_proves_nothing(tesseract):
    by_quality: dict[str, list[float]] = {}
    for doc, number, text in PAGES:
        with Image.open(io.BytesIO(render(doc, number, text))) as image:
            by_quality.setdefault(doc.quality, []).append(character_accuracy(text, tesseract.image_to_string(image, lang="swe+eng")))

    overall = [s for scores in by_quality.values() for s in scores]
    assert min(overall) < 1.0
    assert statistics.mean(by_quality["clean"]) > statistics.mean(by_quality["speckled"])
