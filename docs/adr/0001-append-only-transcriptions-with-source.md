# Transcriptions are append-only and carry their source

The brief's `layer enum(ocr, verified)` is replaced by `source enum(machine, human)`, with engine or author recorded on every row. A person's correction adds a Human transcription instead of replacing anything, so edit history and provenance are preserved. This follows IIIF Presentation 3.0 and W3C Web Annotation, where OCR and manual transcriptions are the same kind of annotation and differ only by creator. Current text and the public "verified" flag are derived from the rows; the staff workflow lives separately in `image.status`.
