from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from docminer.api import create_app
from docminer.settings import Settings

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def make_pdf(pages: list[str | None]) -> bytes:
    """Teszt-PDF. Szöveg = digitális oldal; None = szövegréteg nélküli (szkennelt) oldal."""
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page(width=595, height=842)
        if text is None:
            page.draw_rect(pymupdf.Rect(50, 50, 300, 200), color=(0, 0, 0), fill=(0.5, 0.5, 0.5))
        else:
            page.insert_text((72, 72), text, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        data_dir=tmp_path / "data",
        config_dir=CONFIG_DIR,
        max_upload_mb=5,
        max_pages=50,
        render_dpi=50,
        max_step_attempts=2,
    )


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def invoice_pdf() -> bytes:
    return make_pdf(
        [
            "SZAMLA  Szamlaszam: 2026/0042\nKelte: 2026.11.10\nElado: Minta Kft.  Adoszam: 12345678-2-42\nBrutto: 127 000 HUF",
            None,
        ]
    )
