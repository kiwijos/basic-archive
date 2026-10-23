"""Renders a typed Swedish page with known text, for checking OCR end to end.

Usage: make_scan.py OUTPUT.png [RUN_ID]

Writes the PNG, embedding RUN_ID so every run's file is different (otherwise a second run would be
flagged as a duplicate upload), and prints the exact text on the page so the caller can compare.
Run with: uv run --no-project --with pillow==11.3.0 python scripts/make_scan.py ...
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo

FONT = Path(__file__).resolve().parent / "fonts" / "DejaVuSans.ttf"
LINES = ["Skeppet Vega lämnade Göteborg", "den 14 mars 1891 med last av järn och trä."]


def main() -> None:
    output = sys.argv[1]
    run_id = sys.argv[2] if len(sys.argv) > 2 else "manual"
    font = ImageFont.truetype(str(FONT), 56)
    page = Image.new("L", (1900, 320), 255)
    draw = ImageDraw.Draw(page)
    for number, line in enumerate(LINES):
        draw.text((40, 40 + number * 106), line, font=font, fill=0)
    marker = PngInfo()
    marker.add_text("Comment", f"smoke run {run_id}")
    page.save(output, format="PNG", pnginfo=marker)
    print(" ".join(" ".join(LINES).split()))


if __name__ == "__main__":
    main()
