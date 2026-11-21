"""Folytatható feldolgozási lánc.

Minden irat minden lépése külön állapotot kap. A futtató sorban halad, a kész
lépést átugorja, így leállás vagy hiba után onnan folytat, ahol abbahagyta.
A lépések idempotensek: újrafuttatáskor felülírják a saját korábbi kimenetüket.

Az 1. körben megvalósított lépések: oldalbontás, szövegkinyerés, csomagkészítés.
A tervezett hat lépésből a többi (felmérés/DocSorter, képi részek, összerendelés,
ellenőrzés) ugyanide kerül be új `Step`-ként.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

import pymupdf
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import __version__
from .db import Database
from .extract import extract_page
from .intake import render_page_png
from .model_config import load_model_config
from .models import Document, DocStatus, JobStep, Page, StepStatus, UsageRecord
from .providers import BudgetExceeded, OcrPageInput, ProviderRegistry, call_ocr, default_registry
from .settings import Settings, models_path
from .storage import LocalStorage

log = logging.getLogger(__name__)


@dataclass
class StepContext:
    session: Session
    doc: Document
    storage: LocalStorage
    settings: Settings
    registry: ProviderRegistry | None = None

    def open_original(self) -> pymupdf.Document:
        data = self.storage.get_bytes(LocalStorage.original_key(self.doc.id, self.doc.filename))
        ftype = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg", "image/tiff": "tiff"}[self.doc.mime]
        return pymupdf.open(stream=data, filetype=ftype)


StepFn = Callable[[StepContext], dict]


@dataclass(frozen=True)
class Step:
    name: str
    fn: StepFn


# --- Lépések ---------------------------------------------------------------


def step_split_pages(ctx: StepContext) -> dict:
    """Oldalakra bontás: oldalkép (PNG) és oldalsor az adatbázisban."""
    ctx.session.execute(delete(Page).where(Page.document_id == ctx.doc.id))
    with ctx.open_original() as pdf:
        for page in pdf:
            n = page.number + 1
            key = ctx.storage.put_bytes(
                LocalStorage.page_image_key(ctx.doc.id, n), render_page_png(page, ctx.settings.render_dpi)
            )
            ctx.session.add(
                Page(document_id=ctx.doc.id, number=n, width=page.rect.width, height=page.rect.height, image_path=key)
            )
        ctx.doc.page_count = pdf.page_count
    return {"pages": ctx.doc.page_count, "dpi": ctx.settings.render_dpi, "tool": f"pymupdf {pymupdf.VersionBind}"}


def step_extract_text(ctx: StepContext) -> dict:
    """Szöveg, szavak, blokkok és táblák koordinátákkal; a szöveg nélküli oldal OCR-re vár."""
    pages = {p.number: p for p in ctx.session.scalars(select(Page).where(Page.document_id == ctx.doc.id))}
    digital = scanned = tables = 0
    with ctx.open_original() as pdf:
        for page in pdf:
            ex = extract_page(page)
            row = pages[ex.number]
            row.kind, row.text, row.char_count = ex.kind, ex.text, ex.char_count
            ctx.storage.put_text(LocalStorage.page_text_key(ctx.doc.id, ex.number), ex.text)
            ctx.storage.put_json(LocalStorage.page_layout_key(ctx.doc.id, ex.number), ex.layout())
            digital += ex.kind == "digital"
            scanned += ex.kind == "scanned"
            tables += len(ex.tables)
    return {"digital_pages": digital, "scanned_pages": scanned, "needs_ocr": scanned > 0, "tables": tables, "tool": f"pymupdf {pymupdf.VersionBind}"}


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def ocr_pages_used(session: Session, month: str) -> int:
    """A hónapban valódi (nem próba) OCR-szolgáltatónál felhasznált oldalak."""
    return int(
        session.scalar(
            select(func.coalesce(func.sum(UsageRecord.pages), 0)).where(
                UsageRecord.month == month, UsageRecord.step == "ocr", ~UsageRecord.provider.startswith("fake")
            )
        )
    )


def _single_page_pdf(src: pymupdf.Document, index: int) -> bytes:
    out = pymupdf.open()
    out.insert_pdf(src, from_page=index, to_page=index)
    data = out.tobytes(garbage=3, deflate=True)
    out.close()
    return data


def step_ocr(ctx: StepContext) -> dict:
    """A szövegréteg nélküli (szkennelt) oldalak OCR-je; a már kész oldalt nem küldi újra.

    A modell a models.yaml `ocr` lépéséből jön (élesben Document AI, EU).
    Indítás előtt ellenőrzi a havi oldalkorlátot, így a keret nem lépi túl.
    """
    config = load_model_config(models_path(ctx.settings))
    spec = config.for_step("ocr")
    registry = ctx.registry or default_registry()
    pages = ctx.session.scalars(
        select(Page).where(Page.document_id == ctx.doc.id, Page.kind == "scanned").order_by(Page.number)
    ).all()

    todo, resumed = [], 0
    for p in pages:
        key = LocalStorage.page_layout_key(ctx.doc.id, p.number)
        if ctx.storage.exists(key):
            layout = json.loads(ctx.storage.get_bytes(key))
            if str(layout.get("tool", "")).startswith("ocr:"):
                # Korábbi futásban már kifizetett oldal: csak visszatöltjük.
                p.text = ctx.storage.get_bytes(LocalStorage.page_text_key(ctx.doc.id, p.number)).decode("utf-8")
                p.char_count = sum(1 for c in p.text if not c.isspace())
                resumed += 1
                continue
        todo.append(p)

    month = _month()
    used = ocr_pages_used(ctx.session, month)
    real = not spec.provider.startswith("fake")
    if real and todo and used + len(todo) > ctx.settings.ocr_monthly_page_limit:
        raise BudgetExceeded(
            f"Havi OCR-korlát: {used} oldal felhasználva, ez az irat még {len(todo)} oldalt kérne, "
            f"a korlát {ctx.settings.ocr_monthly_page_limit} (DOCMINER_OCR_MONTHLY_PAGE_LIMIT)."
        )

    confs, used_model, used_provider = [], spec.model, spec.provider
    if todo:
        with ctx.open_original() as src:
            pdf = src if src.is_pdf else pymupdf.open("pdf", src.convert_to_pdf())
            for p in todo:
                page_input = OcrPageInput(
                    number=p.number, width=p.width, height=p.height, pdf_bytes=_single_page_pdf(pdf, p.number - 1)
                )
                res = call_ocr("ocr", page_input, config, registry)
                p.text = res.text
                p.char_count = sum(1 for c in res.text if not c.isspace())
                ctx.storage.put_text(LocalStorage.page_text_key(ctx.doc.id, p.number), res.text)
                ctx.storage.put_json(
                    LocalStorage.page_layout_key(ctx.doc.id, p.number), res.layout(p.number, p.width, p.height)
                )
                ctx.session.add(
                    UsageRecord(
                        month=month, step="ocr", provider=res.provider, model=res.model,
                        document_id=ctx.doc.id, pages=int(res.usage.get("pages", 1)),
                    )
                )
                used_model, used_provider = res.model, res.provider
                if res.confidence is not None:
                    confs.append(res.confidence)
            if pdf is not src:
                pdf.close()

    return {
        "ocr_pages": len(todo),
        "resumed_pages": resumed,
        "provider": used_provider,
        "model": used_model,
        "avg_confidence": round(sum(confs) / len(confs), 4) if confs else None,
        "month": month,
        "month_pages_used": used + (len(todo) if real else 0),
        "month_page_limit": ctx.settings.ocr_monthly_page_limit,
    }


def step_build_manifest(ctx: StepContext) -> dict:
    """AI-ready csomag: manifest.json az irat mappájában."""
    doc = ctx.doc
    pages = ctx.session.scalars(select(Page).where(Page.document_id == doc.id).order_by(Page.number)).all()
    steps = ctx.session.scalars(select(JobStep).where(JobStep.document_id == doc.id).order_by(JobStep.order)).all()
    manifest = {
        "schema_version": 1,
        "generator": f"docminer {__version__}",
        "document": {
            "id": doc.id,
            "filename": doc.filename,
            "mime": doc.mime,
            "sha256": doc.sha256,
            "size_bytes": doc.size_bytes,
            "page_count": doc.page_count,
            "original": LocalStorage.original_key(doc.id, doc.filename),
        },
        "pages": [
            {
                "number": p.number,
                "width": p.width,
                "height": p.height,
                "kind": p.kind,
                "char_count": p.char_count,
                "image": p.image_path,
                "text": LocalStorage.page_text_key(doc.id, p.number),
                "layout": LocalStorage.page_layout_key(doc.id, p.number),
            }
            for p in pages
        ],
        "steps": [
            {"name": s.name, "status": s.status, "output": s.output}
            for s in steps
            if s.name != "build_manifest"
        ],
        # A későbbi lépések (besorolás, kinyerés, második olvasó) ide írják a megfigyeléseket:
        # {field, value, page, bbox, tool, model, confidence, status: biztos|kétes|eltérő}
        "observations": [],
    }
    key = ctx.storage.put_json(LocalStorage.manifest_key(doc.id), manifest)
    return {"manifest": key}


PIPELINE: list[Step] = [
    Step("split_pages", step_split_pages),
    Step("extract_text", step_extract_text),
    Step("ocr", step_ocr),
    Step("build_manifest", step_build_manifest),
]


# --- Megjelenítéshez: a teljes tervezett folyamat ------------------------
# A DocMaster ebből rajzolja ki a folyamatot. Az `implemented=False` szakaszok
# a terv későbbi lépései; amikor elkészülnek, a `step` mező a PIPELINE lépésére mutat.


@dataclass(frozen=True)
class Stage:
    key: str
    label: str
    module: str
    step: str | None  # a PIPELINE lépésének neve; None = még nincs megvalósítva
    description: str

    @property
    def implemented(self) -> bool:
        return self.step is not None or self.key == "intake"


STAGES: list[Stage] = [
    Stage("intake", "Befogadás", "DocMiner", None, "fájlellenőrzés, duplikációszűrés, eredeti megőrzése"),
    Stage("split_pages", "Oldalbontás", "DocMiner", "split_pages", "oldalanként kép"),
    Stage("docsorter", "Besorolás", "DocSorter", None, "irattípus és mezőcsoportok"),
    Stage("extract_text", "Szöveg és táblák", "DocMiner", "extract_text", "digitális PDF, PyMuPDF"),
    Stage("ocr", "OCR", "DocMiner", "ocr", "szkennelt oldalak, Document AI (EU)"),
    Stage("visual", "Képi részek", "DocMiner", None, "aláírás, bélyegző, kézírás"),
    Stage("fields", "Mezők összerendelése", "DocMiner", None, "a típus YAML-ja szerint, forráshellyel"),
    Stage("verify", "Ellenőrzés", "DocMiner", None, "második olvasó, kétes jelölés"),
    Stage("build_manifest", "AI-ready csomag", "DocMiner", "build_manifest", "manifest.json"),
    Stage("review", "Emberi átnézés", "DocMaster", None, "kétes értékek jóváhagyása"),
]


# --- Futtató ---------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_steps(session: Session, doc: Document, pipeline: list[Step] = PIPELINE) -> None:
    for i, step in enumerate(pipeline):
        session.add(JobStep(document_id=doc.id, name=step.name, order=i))


def run_document(
    db: Database,
    doc_id: str,
    storage: LocalStorage,
    settings: Settings,
    pipeline: list[Step] = PIPELINE,
    registry: ProviderRegistry | None = None,
) -> str:
    """Az irat hátralévő lépéseinek futtatása. Az irat végső állapotát adja vissza."""
    from .budget import UsageGuard

    registry = registry or default_registry()
    for step in pipeline:
        registry.guard = UsageGuard(db, settings, document_id=doc_id, step=step.name)
        with db.session() as s:
            doc = s.get(Document, doc_id)
            js = s.scalar(select(JobStep).where(JobStep.document_id == doc_id, JobStep.name == step.name))
            if js is None:  # új lépés került a láncba a feltöltés után
                js = JobStep(document_id=doc_id, name=step.name, order=pipeline.index(step), status=StepStatus.PENDING, attempts=0)
                s.add(js)
            if js.status == StepStatus.DONE:
                continue
            if js.attempts >= settings.max_step_attempts:
                doc.status, doc.locked_by, doc.locked_at = DocStatus.FAILED, None, None
                doc.error = f"{step.name}: {js.error}"
                return doc.status
            js.status, js.started_at, js.error = StepStatus.RUNNING, _now(), None
            js.attempts += 1
        # A lépés saját tranzakcióban fut; hibánál semmi sem marad félig az adatbázisban.
        try:
            with db.session() as s:
                doc = s.get(Document, doc_id)
                output = step.fn(StepContext(session=s, doc=doc, storage=storage, settings=settings, registry=registry))
                js = s.scalar(select(JobStep).where(JobStep.document_id == doc_id, JobStep.name == step.name))
                js.status, js.output, js.finished_at = StepStatus.DONE, output, _now()
        except Exception as exc:
            log.exception("Lépés hiba: %s / %s", doc_id, step.name)
            with db.session() as s:
                doc = s.get(Document, doc_id)
                js = s.scalar(select(JobStep).where(JobStep.document_id == doc_id, JobStep.name == step.name))
                js.status, js.error, js.finished_at = StepStatus.FAILED, f"{type(exc).__name__}: {exc}", _now()
                # Elfogyott keretnél nincs értelme újrapróbálni: korlátemelés után a retry indítja újra.
                final = isinstance(exc, BudgetExceeded) or js.attempts >= settings.max_step_attempts
                doc.status = DocStatus.FAILED if final else DocStatus.QUEUED
                doc.error = f"{step.name}: {js.error}"
                doc.locked_by = doc.locked_at = None
                return doc.status
    with db.session() as s:
        doc = s.get(Document, doc_id)
        doc.status, doc.error, doc.locked_by, doc.locked_at = DocStatus.DONE, None, None, None
        return doc.status
