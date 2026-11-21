"""Szövegkinyerés PyMuPDF-fel digitális PDF-ből, koordinátákkal.

Ha egy oldalon nincs érdemi szövegréteg, "scanned" jelölést kap: ezt később
a Document AI OCR-adapter dolgozza fel. Minden szó és blokk mellett ott a bbox
(PDF-pont, bal felső sarok az origó), hogy minden érték visszavezethető legyen.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pymupdf

# Ennyi nem szóköz karakter alatt az oldalt szkenneltnek tekintjük.
MIN_DIGITAL_CHARS = 20


@dataclass
class PageExtraction:
    number: int
    width: float
    height: float
    kind: str  # "digital" | "scanned"
    text: str
    char_count: int
    words: list[dict] = field(default_factory=list)
    blocks: list[dict] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)

    def layout(self) -> dict:
        return {
            "page": self.number,
            "width": self.width,
            "height": self.height,
            "kind": self.kind,
            "tool": f"pymupdf {pymupdf.VersionBind}",
            "words": self.words,
            "blocks": self.blocks,
            "tables": self.tables,
        }


def _bbox(r) -> list[float]:
    return [round(float(v), 2) for v in r]


def _tables(page: pymupdf.Page) -> list[dict]:
    try:
        found = page.find_tables()
    except Exception:  # táblakeresés hibája ne állítsa meg a szöveget
        return []
    out = []
    for t in found.tables:
        rows = t.extract()
        out.append(
            {
                "bbox": _bbox(t.bbox),
                "header": [c or "" for c in (t.header.names if t.header else [])],
                "rows": [[c if c is not None else "" for c in row] for row in rows],
            }
        )
    return out


def extract_page(page: pymupdf.Page, *, with_tables: bool = True) -> PageExtraction:
    text = page.get_text("text", sort=True)
    char_count = sum(1 for c in text if not c.isspace())
    kind = "digital" if char_count >= MIN_DIGITAL_CHARS else "scanned"
    words = [
        {"text": w[4], "bbox": _bbox(w[:4]), "block": w[5], "line": w[6]}
        for w in page.get_text("words", sort=True)
    ]
    blocks = [
        {"text": b[4].strip(), "bbox": _bbox(b[:4]), "type": "image" if b[6] else "text"}
        for b in page.get_text("blocks", sort=True)
    ]
    tables = _tables(page) if (with_tables and kind == "digital") else []
    return PageExtraction(
        number=page.number + 1,
        width=round(page.rect.width, 2),
        height=round(page.rect.height, 2),
        kind=kind,
        text=text,
        char_count=char_count,
        words=words,
        blocks=blocks,
        tables=tables,
    )
