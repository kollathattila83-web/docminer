"""Befogadás: fájlellenőrzés, hash, oldalbontás.

Keretrendszertől független: bájtokon és PyMuPDF-dokumentumon dolgozik,
így más projektben (pl. szkennermappa-figyelő) is újrahasznosítható.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pymupdf

# Mágikus bájtok -> (MIME, PyMuPDF filetype)
_SIGNATURES: list[tuple[bytes, str, str]] = [
    (b"%PDF-", "application/pdf", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"II*\x00", "image/tiff", "tiff"),
    (b"MM\x00*", "image/tiff", "tiff"),
]

ACCEPTED_MIME = sorted({m for _, m, _ in _SIGNATURES})


class IntakeError(ValueError):
    """Az irat nem fogadható be; az üzenet a felhasználónak szól."""


@dataclass(frozen=True)
class CheckedFile:
    mime: str
    filetype: str
    sha256: str
    size_bytes: int
    page_count: int


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def detect_type(data: bytes) -> tuple[str, str]:
    """A tartalom alapján dönt, nem a kiterjesztés alapján."""
    head = data[:1024]
    for sig, mime, ftype in _SIGNATURES:
        # A PDF-fejléc előtt lehet szemét (ezt a PDF-olvasók is tűrik).
        if head.startswith(sig) or (ftype == "pdf" and sig in head):
            return mime, ftype
    raise IntakeError(
        "Nem támogatott fájltípus. Elfogadott: PDF, PNG, JPEG, TIFF."
    )


def open_document(data: bytes, filetype: str) -> pymupdf.Document:
    try:
        return pymupdf.open(stream=data, filetype=filetype)
    except Exception as exc:  # PyMuPDF többféle kivételt dob sérült fájlra
        raise IntakeError(f"A fájl sérült vagy nem olvasható: {exc}") from exc


def check_file(data: bytes, *, max_bytes: int, max_pages: int) -> CheckedFile:
    if not data:
        raise IntakeError("Üres fájl.")
    if len(data) > max_bytes:
        raise IntakeError(
            f"A fájl túl nagy ({len(data) / 1e6:.1f} MB, a határ {max_bytes / 1e6:.0f} MB)."
        )
    mime, ftype = detect_type(data)
    with open_document(data, ftype) as doc:
        if doc.needs_pass:
            raise IntakeError("Jelszóval védett PDF; jelszó nélkül nem dolgozható fel.")
        n = doc.page_count
    if n < 1:
        raise IntakeError("A fájlban nincs oldal.")
    if n > max_pages:
        raise IntakeError(f"Túl sok oldal ({n}, a határ {max_pages}).")
    return CheckedFile(mime=mime, filetype=ftype, sha256=sha256_hex(data), size_bytes=len(data), page_count=n)


def render_page_png(page: pymupdf.Page, dpi: int) -> bytes:
    return page.get_pixmap(dpi=dpi).tobytes("png")
