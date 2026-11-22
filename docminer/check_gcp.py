"""Google Cloud kapcsolat ellenőrzése egy-egy apró hívással (költsége elhanyagolható).

Futtatás: docker compose run --rm worker python -m docminer.check_gcp
"""

from __future__ import annotations

import sys

import pymupdf

from .model_config import load_model_config
from .providers import OcrPageInput, PageInput, ProviderRequest, call_ocr, call_step, default_registry
from .settings import get_settings, models_path


def run_checks(settings=None) -> dict:
    """Egy apró OCR- és egy modellhívás; az eredményt szótárban adja vissza (a felület is ezt hívja)."""
    settings = settings or get_settings()
    cfg = load_model_config(models_path(settings))
    reg = default_registry()
    out: dict = {"models_file": settings.models_file, "ocr": None, "model": None, "ok": True}

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "DocMiner proba 2026", fontsize=28)
    # Képpé alakítjuk, hogy valódi OCR-feladat legyen (ne szövegréteget olvasson).
    pix = page.get_pixmap(dpi=200)
    img_pdf = pymupdf.open()
    img_pdf.new_page(width=595, height=842).insert_image(page.rect, pixmap=pix)
    try:
        res = call_ocr("ocr", OcrPageInput(1, 595, 842, img_pdf.tobytes()), cfg, reg)
        out["ocr"] = {"ok": True, "provider": res.provider, "model": res.model, "text": res.text.strip()}
    except Exception as exc:
        out["ok"] = False
        out["ocr"] = {"ok": False, "error": str(exc)}

    req = ProviderRequest(
        task="classify",
        instructions="Add vissza a szövegben szereplő évszámot.",
        schema={"type": "object", "properties": {"year": {"type": "integer"}}, "required": ["year"]},
        pages=[PageInput(1, text="DocMiner próba 2026")],
    )
    try:
        r = call_step("docsorter", req, cfg, reg)
        out["model"] = {"ok": True, "provider": r.provider, "model": r.model, "model_version": r.model_version,
                        "answer": r.data, "usage": r.usage}
    except Exception as exc:
        out["ok"] = False
        out["model"] = {"ok": False, "error": str(exc)}
    return out


def main() -> int:
    r = run_checks()
    print(f"Modellprofil: {r['models_file']}")
    o, m = r["ocr"], r["model"]
    print(f"OCR rendben ({o['provider']}/{o['model']}): {o['text']!r}" if o["ok"] else f"OCR HIBA: {o['error']}")
    print(
        f"Modell rendben ({m['provider']}/{m['model']}, {m['model_version']}): {m['answer']}, tokenek: {m['usage']}"
        if m["ok"] else f"MODELL HIBA: {m['error']}"
    )
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
