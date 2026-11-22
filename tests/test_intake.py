import pytest

from docminer.intake import IntakeError, check_file, detect_type, sha256_hex
from docminer.storage import safe_filename

from .conftest import make_pdf

MB = 1024 * 1024


def test_pdf_accepted(invoice_pdf):
    c = check_file(invoice_pdf, max_bytes=5 * MB, max_pages=10)
    assert c.mime == "application/pdf"
    assert c.page_count == 2
    assert c.sha256 == sha256_hex(invoice_pdf)


def test_type_by_content_not_extension():
    assert detect_type(b"\x89PNG\r\n\x1a\n....")[0] == "image/png"
    assert detect_type(b"\xff\xd8\xff\xe0....")[0] == "image/jpeg"
    with pytest.raises(IntakeError, match="Nem támogatott"):
        detect_type(b"PK\x03\x04 docx = zip")


@pytest.mark.parametrize(
    ("data", "msg"),
    [
        (b"", "Üres"),
        (b"%PDF-1.7 csonka szemet", "sérült"),
    ],
)
def test_rejects_bad_files(data, msg):
    with pytest.raises(IntakeError, match=msg):
        check_file(data, max_bytes=5 * MB, max_pages=10)


def test_rejects_too_big_and_too_many_pages():
    pdf = make_pdf(["a"] * 5)
    with pytest.raises(IntakeError, match="túl nagy"):
        check_file(pdf, max_bytes=10, max_pages=10)
    with pytest.raises(IntakeError, match="Túl sok oldal"):
        check_file(pdf, max_bytes=5 * MB, max_pages=3)


def test_rejects_encrypted_pdf():
    import pymupdf

    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "titkos")
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    with pytest.raises(IntakeError, match="Jelszóval"):
        check_file(data, max_bytes=5 * MB, max_pages=10)


def test_image_is_one_page():
    import pymupdf

    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 30), False)
    pix.clear_with(255)
    c = check_file(pix.tobytes("png"), max_bytes=5 * MB, max_pages=10)
    assert (c.mime, c.page_count) == ("image/png", 1)


def test_safe_filename():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("számla 2026/11.pdf") == "11.pdf"
    assert safe_filename("Szerződés (1).pdf") == "Szerződés _1_.pdf"
    assert safe_filename("") == "upload"
