import io
from dataclasses import dataclass
from functools import cache

import pytesseract
from PIL import Image, ImageOps, UnidentifiedImageError
from pytesseract import Output

ENGINE = "tesseract"


class UnreadableImage(Exception):
    """The file is not an image the worker can open, or is too large to open safely."""


@dataclass(frozen=True)
class Reading:
    text: str
    confidence: float | None
    engine: str
    engine_version: str
    language: str


@cache
def engine_version() -> str:
    return str(pytesseract.get_tesseract_version())


def read(data: bytes, languages: str, max_side: int, max_pixels: int, timeout: int) -> Reading:
    """Read the text of one page image. Only the first page of a multi-page TIFF is read."""
    page = _prepare(data, max_side, max_pixels)
    result = pytesseract.image_to_data(page, lang=languages, output_type=Output.DICT, timeout=timeout)
    text, confidence = _assemble(result)
    return Reading(text, confidence, ENGINE, engine_version(), languages)


def _prepare(data: bytes, max_side: int, max_pixels: int) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        if image.width * image.height > max_pixels:
            raise UnreadableImage(f"{image.width}x{image.height} pixels is above the {max_pixels} pixel limit")
        image.load()
        image = ImageOps.exif_transpose(image).convert("L")
    except UnreadableImage:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError) as error:
        raise UnreadableImage(str(error)) from error
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)  # only ever shrinks
    return image


def _assemble(result: dict) -> tuple[str, float | None]:
    """Rebuild the text in reading order, a blank line between paragraphs, and average the word confidences."""
    lines: dict[tuple[int, int, int], list[str]] = {}
    confidences: list[float] = []
    for index, word in enumerate(result["text"]):
        if not word.strip():
            continue
        key = (result["block_num"][index], result["par_num"][index], result["line_num"][index])
        lines.setdefault(key, []).append(word)
        confidence = float(result["conf"][index])
        if confidence >= 0:
            confidences.append(confidence)
    rows: list[str] = []
    previous = None
    for (block, paragraph, _), words in lines.items():
        if previous is not None and (block, paragraph) != previous:
            rows.append("")
        rows.append(" ".join(words))
        previous = (block, paragraph)
    mean = sum(confidences) / len(confidences) / 100 if confidences else None
    return "\n".join(rows), mean
