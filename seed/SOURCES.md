# Where the demo data comes from

Everything `make demo` loads is one of two kinds. Nothing is copied from an archive, a book or a website whose
terms are unclear, and nothing here names a real person (see ADR 0002).

## 1. Synthetic: invented for this archive

The fleet (4 ships and 3 organisations), their names, owners and dates, and the 13 documents (14 pages) are made up.
They carry the source system `seed`, and the text of every Document says "Synthetic demo document: fictional text
written for this archive". The texts are original Swedish prose written for this project; the scans are rendered from
them by [render.py](src/archive_seed/render.py) with the DejaVu fonts (see below) and look aged on purpose (clean,
faded, skewed and speckled; PNG, JPEG and TIFF). Because the text on every page is known exactly, the OCR can be
measured against it. Rights on these Documents: `CC0`.

## 2. Public domain: Chapman's plates from Wikimedia Commons

Four plates from Fredrik Henrik af Chapman's *Architectura Navalis Mercatoria* (Stockholm, 1768). Chapman died in
1808, so the rights in his work ran out long ago, and Commons files the images as public domain (template
`PD-old-100`). They carry the source system `wikimedia-commons`, rights `PDM`, and a description that names the author,
the licence, the Commons page and the checksum. They are drawings, so the OCR has nothing to read: a person's note
"[Ritning utan löpande text]" stands in for the text and they are left out of the accuracy figures.

They are **not stored in this repository**. `make seed` fetches each one by its exact address, checks its SHA-256
against the value recorded in [plates.py](src/archive_seed/plates.py), keeps it in `~/.cache/archive-seed/plates`, and
refuses (and uploads nothing) if it does not match. Without a network they are skipped, with a message.

| Plate (Commons file page) | Used in | Size | SHA-256 |
|---|---|---|---|
| [Chapman Hagboat VIII.jpg](https://commons.wikimedia.org/wiki/File:Chapman_Hagboat_VIII.jpg) | `plate-hagboat`, sheet 1 | 8928 × 6383 px, 8.3 MB | `4e7a915faac14845af6a7dd1ef06ee5f5d78a02661bf176e072c0dfa5dfa5f20` |
| [Chapman Hagboat IX.jpg](https://commons.wikimedia.org/wiki/File:Chapman_Hagboat_IX.jpg) | `plate-hagboat`, sheet 2 | 9000 × 6503 px, 10.0 MB | `da4733029cb80d105fa539cb59f48b7ff67336c3bc1c883fc2b1dff89b77bf18` |
| [Plate 40 Architectura navalis mercatoria.JPG](https://commons.wikimedia.org/wiki/File:Plate_40_Architectura_navalis_mercatoria.JPG) | `plate-40` | 8880 × 6574 px, 10.6 MB | `20316fa984e21e7713b327d83ec4961d535c68451e8ccd50b0e3304a8fb3245a` |
| [Schooner 1700s Chapman.JPG](https://commons.wikimedia.org/wiki/File:Schooner_1700s_Chapman.JPG) | `plate-schooner` | 2605 × 1901 px, 0.7 MB | `70620706e5c9423eacfd36994051f93e746b27da43d03823a93207a567897c1f` |

The Commons file pages were read, and the sizes, dimensions and SHA-1 values compared with what Commons reports, on
2026-10-24. The SHA-1 of each file is recorded in `plates.py` as that evidence.

## 3. Tools in the seed

The scans are drawn with DejaVu Serif, Sans and Sans Mono (version 2.37), which are free to use and redistribute under
the licence in [src/archive_seed/fonts/LICENSE-DejaVu.txt](src/archive_seed/fonts/LICENSE-DejaVu.txt).
