"""DocMiner REST API. A DocMaster (és bármely más alkalmazás) csak ezen át beszél a motorral.

Futtatás: uvicorn docminer.api:app
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from . import __version__
from .db import Database
from .doctypes import load_doctypes
from .intake import ACCEPTED_MIME, IntakeError, check_file
from .model_config import load_model_config
from .models import Document, DocStatus, JobStep, Page, StepStatus
from .pipeline import STAGES, create_steps
from .settings import Settings, get_settings, models_path
from .storage import LocalStorage, safe_filename

_CHUNK = 1024 * 1024


def _doc_summary(doc: Document) -> dict:
    return {
        "id": doc.id,
        "filename": doc.filename,
        "mime": doc.mime,
        "sha256": doc.sha256,
        "size_bytes": doc.size_bytes,
        "page_count": doc.page_count,
        "status": doc.status,
        "error": doc.error,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    db = Database(settings.database_url)
    db.create_all()
    storage = LocalStorage(settings.data_dir)

    app = FastAPI(title="DocMiner API", version=__version__)
    app.state.settings, app.state.db, app.state.storage = settings, db, storage

    def session():
        with db.session() as s:
            yield s

    def get_doc(doc_id: str, s=Depends(session)) -> Document:
        doc = s.get(Document, doc_id)
        if doc is None:
            raise HTTPException(404, "Nincs ilyen irat.")
        return doc

    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__, "database": db.engine.dialect.name}

    @app.post("/documents", status_code=201)
    async def upload(file: UploadFile, request: Request):
        max_bytes = settings.max_upload_mb * 1024 * 1024
        buf = bytearray()
        while chunk := await file.read(_CHUNK):
            buf.extend(chunk)
            if len(buf) > max_bytes:
                raise HTTPException(413, f"A fájl nagyobb, mint {settings.max_upload_mb} MB.")
        data = bytes(buf)
        try:
            checked = check_file(data, max_bytes=max_bytes, max_pages=settings.max_pages)
        except IntakeError as exc:
            raise HTTPException(422, str(exc)) from exc

        filename = safe_filename(file.filename or "upload")
        with db.session() as s:
            existing = s.scalar(select(Document).where(Document.sha256 == checked.sha256))
            if existing is not None:
                return JSONResponse({**_doc_summary(existing), "duplicate": True}, status_code=200)
            doc = Document(
                sha256=checked.sha256,
                filename=filename,
                mime=checked.mime,
                size_bytes=checked.size_bytes,
                page_count=checked.page_count,
                status=DocStatus.QUEUED,
            )
            s.add(doc)
            try:
                s.flush()
            except IntegrityError:  # két egyidejű feltöltés ugyanazzal a fájllal
                s.rollback()
                existing = s.scalar(select(Document).where(Document.sha256 == checked.sha256))
                return JSONResponse({**_doc_summary(existing), "duplicate": True}, status_code=200)
            # Az eredeti fájl érintetlenül kerül a tárolóba, mielőtt a sorba állna.
            storage.put_bytes(LocalStorage.original_key(doc.id, filename), data)
            create_steps(s, doc)
            return {**_doc_summary(doc), "duplicate": False}

    @app.get("/documents")
    def list_documents(
        status: str | None = None,
        q: str | None = Query(None, description="keresés a fájlnévben"),
        limit: int = Query(50, le=500),
        offset: int = 0,
        s=Depends(session),
    ):
        stmt = select(Document)
        if status:
            stmt = stmt.where(Document.status == status)
        if q:
            stmt = stmt.where(Document.filename.ilike(f"%{q}%"))
        total = s.scalar(select(func.count()).select_from(stmt.subquery()))
        docs = s.scalars(stmt.order_by(Document.created_at.desc()).limit(limit).offset(offset)).all()
        return {"total": total, "items": [_doc_summary(d) for d in docs]}

    @app.get("/documents/{doc_id}")
    def document_detail(doc: Document = Depends(get_doc)):
        return {
            **_doc_summary(doc),
            "steps": [
                {
                    "name": st.name,
                    "status": st.status,
                    "attempts": st.attempts,
                    "error": st.error,
                    "output": st.output,
                    "started_at": st.started_at.isoformat() if st.started_at else None,
                    "finished_at": st.finished_at.isoformat() if st.finished_at else None,
                }
                for st in doc.steps
            ],
            "pages": [
                {"number": p.number, "kind": p.kind, "char_count": p.char_count, "width": p.width, "height": p.height}
                for p in doc.pages
            ],
        }

    def _page(doc: Document, number: int) -> Page:
        page = next((p for p in doc.pages if p.number == number), None)
        if page is None:
            raise HTTPException(404, "Nincs ilyen oldal (vagy még nincs feldolgozva).")
        return page

    @app.get("/documents/{doc_id}/pages/{number}/text", response_class=PlainTextResponse)
    def page_text(number: int, doc: Document = Depends(get_doc)):
        page = _page(doc, number)
        if page.text is None:
            raise HTTPException(409, "A szövegkinyerés még nem futott le.")
        return page.text

    @app.get("/documents/{doc_id}/pages/{number}/layout")
    def page_layout(number: int, doc: Document = Depends(get_doc)):
        key = LocalStorage.page_layout_key(doc.id, _page(doc, number).number)
        if not storage.exists(key):
            raise HTTPException(409, "A szövegkinyerés még nem futott le.")
        return FileResponse(storage.path(key), media_type="application/json")

    @app.get("/documents/{doc_id}/pages/{number}/image")
    def page_image(number: int, doc: Document = Depends(get_doc)):
        page = _page(doc, number)
        if not page.image_path or not storage.exists(page.image_path):
            raise HTTPException(409, "Az oldalkép még nem készült el.")
        return FileResponse(storage.path(page.image_path), media_type="image/png")

    @app.get("/documents/{doc_id}/original")
    def original(doc: Document = Depends(get_doc)):
        return FileResponse(
            storage.path(LocalStorage.original_key(doc.id, doc.filename)), media_type=doc.mime, filename=doc.filename
        )

    @app.get("/documents/{doc_id}/manifest")
    def manifest(doc: Document = Depends(get_doc)):
        key = LocalStorage.manifest_key(doc.id)
        if not storage.exists(key):
            raise HTTPException(409, "A csomag még nem készült el.")
        return FileResponse(storage.path(key), media_type="application/json")

    @app.post("/documents/{doc_id}/retry")
    def retry(doc: Document = Depends(get_doc), s=Depends(session)):
        """A hibás lépések újraindítása; a kész lépések nem futnak újra."""
        if doc.status not in (DocStatus.FAILED,):
            raise HTTPException(409, f"Csak hibás irat indítható újra (most: {doc.status}).")
        for st in s.scalars(select(JobStep).where(JobStep.document_id == doc.id)):
            if st.status != StepStatus.DONE:
                st.status, st.attempts, st.error = StepStatus.PENDING, 0, None
        doc.status, doc.error = DocStatus.QUEUED, None
        return _doc_summary(doc)

    @app.get("/pipeline")
    def pipeline_overview(limit: int = Query(200, le=1000), s=Depends(session)):
        """A folyamat áttekintése a DocMaster folyamatnézetéhez: szakaszok, számlálók, iratonkénti állapot."""
        by_status = dict(s.execute(select(Document.status, func.count()).group_by(Document.status)).all())
        step_counts: dict[str, dict[str, int]] = {}
        for name, status, n in s.execute(
            select(JobStep.name, JobStep.status, func.count()).group_by(JobStep.name, JobStep.status)
        ):
            step_counts.setdefault(name, {})[status] = n
        total = sum(by_status.values())

        docs = s.scalars(select(Document).order_by(Document.created_at.desc()).limit(limit)).all()
        ids = [d.id for d in docs]
        steps_by_doc: dict[str, dict[str, dict]] = {i: {} for i in ids}
        scanned: dict[str, list[int]] = {i: [] for i in ids}
        if ids:
            for st in s.scalars(select(JobStep).where(JobStep.document_id.in_(ids))):
                steps_by_doc[st.document_id][st.name] = {"status": st.status, "attempts": st.attempts, "error": st.error}
            for doc_id, number in s.execute(
                select(Page.document_id, Page.number).where(Page.document_id.in_(ids), Page.kind == "scanned")
            ):
                scanned[doc_id].append(number)

        stages = []
        for stg in STAGES:
            if stg.key == "intake":
                counts = {StepStatus.DONE: total}
            elif stg.step:
                counts = step_counts.get(stg.step, {})
            else:
                counts = {}
            stages.append(
                {
                    "key": stg.key,
                    "label": stg.label,
                    "module": stg.module,
                    "description": stg.description,
                    "implemented": stg.implemented,
                    "counts": {k: counts.get(k, 0) for k in StepStatus},
                }
            )

        items = []
        for d in docs:
            cells = {}
            for stg in STAGES:
                if stg.key == "intake":
                    cells[stg.key] = {"status": StepStatus.DONE}
                elif stg.step:
                    cells[stg.key] = steps_by_doc[d.id].get(stg.step, {"status": StepStatus.PENDING})
                else:
                    cells[stg.key] = {"status": "planned"}
            items.append(
                {**_doc_summary(d), "stages": cells, "scanned_pages": sorted(scanned[d.id])}
            )

        return {
            "documents": {"total": total, "by_status": {k: by_status.get(k, 0) for k in DocStatus}},
            "stages": stages,
            "items": items,
        }

    @app.get("/usage")
    def usage(s=Depends(session)):
        """A hónap fizetős felhasználása a korlátokhoz képest."""
        from .budget import UsageGuard, current_month
        from .pipeline import ocr_pages_used

        month = current_month()
        calls, tokens = UsageGuard(db, settings).llm_usage(month)
        return {
            "month": month,
            "ocr_pages": {"used": ocr_pages_used(s, month), "limit": settings.ocr_monthly_page_limit},
            "llm_calls": {"used": calls, "limit": settings.llm_monthly_call_limit},
            "llm_tokens": {"used": tokens, "limit": settings.llm_monthly_token_limit},
            "models_file": settings.models_file,
        }

    @app.get("/config/doctypes")
    def doctypes():
        types = load_doctypes(settings.config_dir / "doctypes")
        return {k: v.model_dump() for k, v in types.items()}

    @app.get("/config/models")
    def models():
        return load_model_config(models_path(settings)).model_dump()

    @app.get("/config/accepted-types")
    def accepted():
        return {"mime": ACCEPTED_MIME, "max_upload_mb": settings.max_upload_mb}

    return app


def __getattr__(name: str):
    # `uvicorn docminer.api:app` lusta létrehozás, hogy a tesztek importja ne nyisson adatbázist.
    if name == "app":
        global app
        app = create_app()
        return app
    raise AttributeError(name)
