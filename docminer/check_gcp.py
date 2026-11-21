"""Google Cloud kapcsolat ellenőrzése egy-egy apró hívással (költsége elhanyagolható).

Futtatás: docker compose run --rm worker python -m docminer.check_gcp
"""

from __future__ import annotations

import sys

import pymupdf

from .model_config import load_model_config
from .providers import OcrPageInput, PageInput, ProviderRequest, call_ocr, call_step, default_registry
from .settings import get_settings, models_path


def main() -> int:
    settings = get_settings()
    cfg = load_model_config(models_path(settings))
    reg = default_registry()
    ok = True
    print(f"Modellprofil: {settings.models_file}")

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "DocMiner proba 2026", fontsize=28)
    # Képpé alakítjuk, hogy valódi OCR-feladat legyen (ne szövegréteget olvasson).
    pix = page.get_pixmap(dpi=200)
    img_pdf = pymupdf.open()
    img_pdf.new_page(width=595, height=842).insert_image(page.rect, pixmap=pix)
    try:
        res = call_ocr("ocr", OcrPageInput(1, 595, 842, img_pdf.tobytes()), cfg, reg)
        print(f"OCR rendben ({res.provider}/{res.model}): {res.text.strip()!r}")
    except Exception as exc:
        ok = False
        print(f"OCR HIBA: {exc}")

    req = ProviderRequest(
        task="classify",
        instructions="Add vissza a szövegben szereplő évszámot.",
        schema={"type": "object", "properties": {"year": {"type": "integer"}}, "required": ["year"]},
        pages=[PageInput(1, text="DocMiner próba 2026")],
    )
    try:
        r = call_step("docsorter", req, cfg, reg)
        print(f"Modell rendben ({r.provider}/{r.model}, {r.model_version}): {r.data}, tokenek: {r.usage}")
    except Exception as exc:
        ok = False
        print(f"MODELL HIBA: {exc}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
