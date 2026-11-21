"""DocSorter: irattípus-javaslat és emberi jóváhagyás.

A gép javasol, ember dönt: a besorolás lépése csak javaslatot ír (típus, bizonyosság,
indoklás). A végleges típust mindig ember hagyja jóvá vagy javítja a DocMasterben.
Minden döntésből tanítópélda lesz (`training/doctype/<id>.json`), ebből később saját
osztályozó (pl. huBERT) tanítható, és mérhető, mennyire pontos a javaslat.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .doctypes import DocType, load_doctypes
from .models import Document, Page, TypeStatus
from .providers.base import PageInput, ProviderRequest
from .storage import LocalStorage

OTHER_TYPE = "egyeb"
OTHER_LABEL = "Egyéb / nem besorolható"
STEP_NAME = "docsorter"  # a config/models.yaml lépésneve


def type_choices(config_dir: Path) -> dict[str, str]:
    """Választható típusok (azonosító -> név). Az „egyéb” mindig az első."""
    types = load_doctypes(config_dir / "doctypes")
    return {OTHER_TYPE: OTHER_LABEL, **{k: t.name for k, t in sorted(types.items())}}


def classify_schema(choices: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "doc_type": {"type": "string", "enum": choices},
            "confidence": {"type": "number"},
            "reason": {"type": "string"},
        },
        "required": ["doc_type", "confidence"],
    }


def build_instructions(types: dict[str, DocType]) -> str:
    lines = [
        "Sorold be a magyar nyelvű iratot az alábbi típusok egyikébe.",
        "Csak az irat tartalma alapján dönts. Ha egyik sem illik, vagy nem tudod eldönteni, "
        f"válaszd ezt: '{OTHER_TYPE}'.",
        "A 'confidence' 0 és 1 közötti szám: mennyire vagy biztos a besorolásban.",
        "A 'reason' egy rövid mondat: mi alapján döntöttél (pl. fejléc, jellemző mezők).",
        "",
        "Típusok:",
    ]
    for key, t in sorted(types.items()):
        lines.append(f"- {key}: {t.name}. {t.description}".rstrip())
    lines.append(f"- {OTHER_TYPE}: {OTHER_LABEL}.")
    return "\n".join(lines)


def build_request(
    doc: Document, pages: list[Page], storage: LocalStorage, config_dir: Path, *, max_pages: int, chars_per_page: int
) -> ProviderRequest:
    types = load_doctypes(config_dir / "doctypes")
    choices = list(type_choices(config_dir))
    inputs = []
    for p in pages[:max_pages]:
        image = str(storage.path(p.image_path)) if p.image_path else None
        inputs.append(PageInput(number=p.number, text=(p.text or "")[:chars_per_page] or None, image_path=image))
    return ProviderRequest(
        task="classify",
        instructions=build_instructions(types),
        schema=classify_schema(choices),
        pages=inputs,
        metadata={"document_id": doc.id, "filename": doc.filename, "page_count": doc.page_count},
    )


def apply_suggestion(doc: Document, data: dict) -> None:
    """A modell javaslatának rögzítése. A korábbi emberi döntést nem írja felül."""
    conf = float(data.get("confidence") or 0.0)
    doc.suggested_type = data["doc_type"]
    doc.suggested_confidence = min(max(conf, 0.0), 1.0)
    doc.suggested_reason = (data.get("reason") or "").strip() or None
    if doc.type_status in (None, TypeStatus.SUGGESTED):
        doc.type_status = TypeStatus.SUGGESTED
        doc.doc_type = None


def classification_block(doc: Document) -> dict:
    """A manifest besorolási része."""
    return {
        "suggested": {
            "doc_type": doc.suggested_type,
            "confidence": doc.suggested_confidence,
            "reason": doc.suggested_reason,
        },
        "doc_type": doc.doc_type,
        "status": doc.type_status,
        "reviewed_by": doc.reviewed_by,
        "reviewed_at": doc.reviewed_at.isoformat() if doc.reviewed_at else None,
    }


def review(doc: Document, doc_type: str, reviewer: str | None, choices: dict[str, str]) -> None:
    """Emberi döntés: elfogadja a javaslatot, vagy más típust választ."""
    if doc_type not in choices:
        raise ValueError(f"Ismeretlen irattípus: '{doc_type}'. Választható: {sorted(choices)}")
    doc.doc_type = doc_type
    doc.type_status = TypeStatus.APPROVED if doc_type == doc.suggested_type else TypeStatus.CORRECTED
    doc.reviewed_by = (reviewer or "").strip()[:100] or None
    doc.reviewed_at = datetime.now(timezone.utc)


def training_example(doc: Document, pages: list[Page]) -> dict:
    """Egy jóváhagyott tanítópélda: a szöveg és az ember által megadott típus."""
    return {
        "schema_version": 1,
        "document_id": doc.id,
        "sha256": doc.sha256,
        "filename": doc.filename,
        "label": doc.doc_type,
        "status": doc.type_status,
        "suggested": doc.suggested_type,
        "suggested_confidence": doc.suggested_confidence,
        "reviewed_by": doc.reviewed_by,
        "reviewed_at": doc.reviewed_at.isoformat() if doc.reviewed_at else None,
        "pages": [{"number": p.number, "kind": p.kind, "text": p.text or ""} for p in pages],
    }


def save_review(storage: LocalStorage, doc: Document, pages: list[Page]) -> None:
    """Tanítópélda mentése és a manifest besorolási részének frissítése."""
    storage.put_json(LocalStorage.training_doctype_key(doc.id), training_example(doc, pages))
    key = LocalStorage.manifest_key(doc.id)
    if storage.exists(key):
        manifest = json.loads(storage.get_bytes(key))
        manifest["classification"] = classification_block(doc)
        storage.put_json(key, manifest)
