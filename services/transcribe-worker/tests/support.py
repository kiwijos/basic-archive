import difflib
import io
import json
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT = Path(__file__).resolve().parents[3] / "scripts" / "fonts" / "DejaVuSans.ttf"

LINES = ["Skeppet Vega lämnade Göteborg", "den 14 mars 1891 med last av järn och trä."]


def scan(lines=LINES, size=(1900, 320), font_size=56, fmt="PNG") -> bytes:
    """A typed page with known Swedish text, rendered with a font that has å, ä and ö."""
    page = Image.new("L", size, 255)
    draw = ImageDraw.Draw(page)
    font = ImageFont.truetype(str(FONT), font_size)
    for number, line in enumerate(lines):
        draw.text((40, 40 + number * int(font_size * 1.9)), line, font=font, fill=0)
    out = io.BytesIO()
    page.save(out, format=fmt)
    return out.getvalue()


def similarity(expected: str, actual: str) -> float:
    """How alike two texts are, ignoring line breaks and spacing; engine versions differ in small ways."""
    return difflib.SequenceMatcher(None, " ".join(expected.split()), " ".join(actual.split())).ratio()


def wait_until(condition, timeout=20.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return condition()


def job(image_id: str, attempt: int = 1) -> bytes:
    return json.dumps({"image_id": image_id, "attempt": attempt}).encode()
