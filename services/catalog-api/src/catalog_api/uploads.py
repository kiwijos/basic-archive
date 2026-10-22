import hashlib
from typing import BinaryIO

# The first bytes of each accepted format. The file's real type is read from these, never from its name.
SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
)

SIGNATURE_LENGTH = max(len(signature) for signature, _ in SIGNATURES)
CHUNK_SIZE = 1024 * 1024


class FileTooLarge(Exception):
    pass


def sniff_mime(content: BinaryIO) -> str | None:
    """The MIME type of an accepted image format, judged by its magic bytes, or None."""
    content.seek(0)
    head = content.read(SIGNATURE_LENGTH)
    content.seek(0)
    for signature, mime in SIGNATURES:
        if head.startswith(signature):
            return mime
    return None


def fingerprint(content: BinaryIO, limit: int) -> str:
    """The SHA-256 of the whole file, read in chunks; raises FileTooLarge past the limit."""
    digest = hashlib.sha256()
    size = 0
    content.seek(0)
    while chunk := content.read(CHUNK_SIZE):
        size += len(chunk)
        if size > limit:
            raise FileTooLarge
        digest.update(chunk)
    content.seek(0)
    return digest.hexdigest()
