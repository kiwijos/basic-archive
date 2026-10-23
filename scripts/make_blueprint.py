"""Draws a large synthetic ship lines plan, to prove deep zoom without depending on anyone else's scan.

Usage: make_blueprint.py OUTPUT.tif [RUN_ID] [WIDTH HEIGHT]

The drawing is our own work and is dedicated to the public domain (CC0). It is a blueprint-style plan
(white lines on blue) with a grid, hull lines, numbered stations and small labels that only become
readable when zoomed in, so smooth zooming is something a person can see. RUN_ID is written into the
title block so every run's file is different (otherwise a second upload would be flagged a duplicate).
Run with: uv run --no-project --with pillow==11.3.0 python scripts/make_blueprint.py ...
"""

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT = Path(__file__).resolve().parent / "fonts" / "DejaVuSans.ttf"
BACKGROUND = (22, 52, 104)
LINE = (232, 240, 255)
FAINT = (70, 104, 164)


def hull_half_breadth(x: float, z: float) -> float:
    """Half the width of the hull at fraction x (0 stern, 1 bow) along its length and z (0 keel, 1 deck) up its depth."""
    fullness = math.sin(math.pi * min(max(x, 0.0), 1.0)) ** 0.7
    return fullness * (0.35 + 0.65 * z) * (1 - 0.15 * (1 - z) ** 2)


def main() -> None:
    output = sys.argv[1]
    run_id = sys.argv[2] if len(sys.argv) > 2 else "manual"
    width = int(sys.argv[3]) if len(sys.argv) > 3 else 9000
    height = int(sys.argv[4]) if len(sys.argv) > 4 else 6000

    image = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    small = ImageFont.truetype(str(FONT), 22)
    medium = ImageFont.truetype(str(FONT), 48)
    large = ImageFont.truetype(str(FONT), 110)

    for x in range(0, width, 100):
        draw.line([(x, 0), (x, height)], fill=FAINT, width=2 if x % 500 == 0 else 1)
    for y in range(0, height, 100):
        draw.line([(0, y), (width, y)], fill=FAINT, width=2 if y % 500 == 0 else 1)

    margin = 400
    length = width - 2 * margin
    sheer_y = height * 0.30
    keel_y = height * 0.62
    depth = keel_y - sheer_y

    # Profile (sheer and keel) with stations every 1/20th of the length, each labelled.
    for station in range(21):
        x = station / 20
        px = margin + x * length
        draw.line([(px, sheer_y - 120), (px, keel_y + 120)], fill=LINE, width=2)
        draw.text((px - 40, sheer_y - 190), f"ST {station}", font=medium, fill=LINE)
        for level in range(1, 10):
            z = level / 10
            py = keel_y - z * depth
            half = hull_half_breadth(x, z) * 380
            draw.line([(px - 8, py), (px + 8, py)], fill=LINE, width=2)
            draw.text((px + 12, py - 12), f"{half:.1f}", font=small, fill=LINE)
    for level in range(0, 11):
        z = level / 10
        points = [(margin + (i / 200) * length, keel_y - z * depth) for i in range(201)]
        draw.line(points, fill=LINE, width=3 if level in (0, 10) else 1)

    # Body plan below: the half-breadth of every station, drawn as one curve per station.
    plan_top = height * 0.70
    for station in range(21):
        x = station / 20
        offset = margin + station * (length / 20)
        side = [(offset + hull_half_breadth(x, z / 40) * 130, plan_top + (1 - z / 40) * 900) for z in range(41)]
        mirrored = [(offset - (px - offset), py) for px, py in side]
        draw.line(side, fill=LINE, width=2)
        draw.line(mirrored, fill=LINE, width=2)
    draw.line([(margin, plan_top + 900), (margin + length, plan_top + 900)], fill=LINE, width=3)

    # Title block.
    draw.rectangle([width - 2600, height - 700, width - 150, height - 120], outline=LINE, width=6)
    draw.text((width - 2500, height - 650), "LINES PLAN", font=large, fill=LINE)
    draw.text((width - 2500, height - 500), "Ship Archive Lite: generated drawing, CC0", font=medium, fill=LINE)
    draw.text((width - 2500, height - 420), f"Scale 1:50   Sheet 1 of 1   Run {run_id}", font=medium, fill=LINE)
    draw.text((width - 2500, height - 340), "Station numbers run from the stern (0) to the bow (20).", font=small, fill=LINE)

    image.save(output, format="TIFF", compression="tiff_adobe_deflate", dpi=(300, 300))
    print(f"{output}: {width}x{height}")


if __name__ == "__main__":
    main()
