"""Draws a page of text as a scan, the same way every time.

A scan is the text on paper, then the flaws of its quality: faded ink, a slight skew, specks. The flaws come
from a random generator seeded with the page's key, so a rerun makes byte-identical files (and so the same
checksums), while different pages get different flaws.
"""

import io
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = Path(__file__).resolve().parent / "fonts"
FILES = {"serif": "DejaVuSerif.ttf", "mono": "DejaVuSansMono.ttf", "sans": "DejaVuSans.ttf"}
MIMES = {"png": "image/png", "jpeg": "image/jpeg", "tiff": "image/tiff"}

WIDTH = 1240  # a page at about 150 dpi
MARGIN = 120
SIZE = {"serif": 32, "mono": 29, "sans": 32}
PAPER = (244, 241, 232)
INK = (24, 22, 20)


def mime_of(fmt: str) -> str:
    return MIMES[fmt]


def _lines(text: str, font: ImageFont.FreeTypeFont) -> list[str]:
    """Greedy word wrap to the width of the page; a line break in the text starts a new line."""
    limit = WIDTH - 2 * MARGIN
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        for word in paragraph.split():
            trial = f"{current} {word}".strip()
            if current and font.getlength(trial) > limit:
                lines.append(current)
                current = word
            else:
                current = trial
        lines.append(current)
    return lines


def _speckle(image: Image.Image, rng: random.Random, count: int) -> None:
    draw = ImageDraw.Draw(image)
    for _ in range(count):
        x, y, r = rng.randrange(image.width), rng.randrange(image.height), rng.choice((1, 1, 2))
        grey = rng.randrange(60, 150)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(grey, grey, grey))


def render_page(text: str, *, font: str, quality: str, fmt: str, key: str) -> bytes:
    rng = random.Random(f"scan:{key}")
    face = ImageFont.truetype(str(FONTS / FILES[font]), SIZE[font])
    lines = _lines(text, face)
    leading = int(SIZE[font] * 1.65)
    height = max(520, 2 * MARGIN + leading * len(lines))

    ink = {"faded": (112, 108, 100), "skewed": (84, 80, 72)}.get(quality, INK)
    page = Image.new("RGB", (WIDTH, height), PAPER)
    draw = ImageDraw.Draw(page)
    for number, line in enumerate(lines):
        draw.text((MARGIN, MARGIN + number * leading), line, font=face, fill=ink)

    if quality == "faded":
        page = page.filter(ImageFilter.GaussianBlur(0.9))
        _speckle(page, rng, 120)
    elif quality == "skewed":
        angle = rng.choice((-1, 1)) * rng.uniform(1.6, 2.6)
        page = page.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=PAPER)
        page = page.crop(((page.width - WIDTH) // 2, 0, (page.width - WIDTH) // 2 + WIDTH, page.height))
        # A page photographed at an angle is also a little soft.
        page = page.filter(ImageFilter.GaussianBlur(1.1))
    elif quality == "speckled":
        _speckle(page, rng, 450)
        shade = Image.linear_gradient("L").resize(page.size).point(lambda v: 255 - v // 7)
        page = Image.composite(page, Image.new("RGB", page.size, (200, 196, 186)), shade)
        page = page.filter(ImageFilter.GaussianBlur(0.7))

    out = io.BytesIO()
    if fmt == "png":
        page.save(out, format="PNG", compress_level=6)
    elif fmt == "jpeg":
        page.save(out, format="JPEG", quality=82)
    elif fmt == "tiff":
        # Uncompressed: the compressed writers leave one byte of padding uninitialised, which would make the
        # same page a different file each time.
        page.save(out, format="TIFF", compression=None)
    else:
        raise ValueError(f"unknown format {fmt}")
    return out.getvalue()
