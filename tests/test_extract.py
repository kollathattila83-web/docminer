import pymupdf

from docminer.extract import extract_page

from .conftest import make_pdf


def test_digital_and_scanned_pages(invoice_pdf):
    with pymupdf.open(stream=invoice_pdf, filetype="pdf") as doc:
        first, second = extract_page(doc[0]), extract_page(doc[1])
    assert first.kind == "digital"
    assert "2026/0042" in first.text
    word = next(w for w in first.words if w["text"] == "2026/0042")
    x0, y0, x1, y1 = word["bbox"]
    assert 0 < x0 < x1 <= first.width and 0 < y0 < y1 <= first.height
    assert second.kind == "scanned"
    assert second.char_count == 0


def test_table_extraction():
    doc = pymupdf.open()
    page = doc.new_page()
    cells = [["Tétel", "Menny.", "Ár"], ["Csavar", "10", "500"], ["Anya", "20", "300"]]
    x0, y0, cw, rh = 72, 100, 120, 24
    for r, row in enumerate(cells):
        for c, val in enumerate(row):
            rect = pymupdf.Rect(x0 + c * cw, y0 + r * rh, x0 + (c + 1) * cw, y0 + (r + 1) * rh)
            page.draw_rect(rect, color=(0, 0, 0), width=0.8)
            page.insert_text((rect.x0 + 4, rect.y1 - 7), val, fontsize=10)
    page.insert_text((72, 80), "Tetelek listaja a szamlan", fontsize=10)
    ex = extract_page(page)
    assert ex.tables, "a táblát meg kell találni"
    flat = [c for row in ex.tables[0]["rows"] for c in row] + ex.tables[0]["header"]
    assert "Csavar" in flat and "500" in flat
