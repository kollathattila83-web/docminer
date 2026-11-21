import json

import pytest
from sqlalchemy import select

from docminer import pipeline as pl
from docminer.models import Document, DocStatus, JobStep, Page, StepStatus
from docminer.worker import drain


def _upload(client, data, name="szamla.pdf"):
    r = client.post("/documents", files={"file": (name, data, "application/pdf")})
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_full_run_creates_ai_ready_package(app, client, settings, invoice_pdf):
    doc = _upload(client, invoice_pdf)
    assert doc["status"] == "queued" and doc["duplicate"] is False
    assert drain(app.state.db, app.state.storage, settings) == 1

    d = client.get(f"/documents/{doc['id']}").json()
    assert d["status"] == "done"
    assert [s["status"] for s in d["steps"]] == ["done"] * 4
    assert [p["kind"] for p in d["pages"]] == ["digital", "scanned"]
    assert d["steps"][1]["output"]["needs_ocr"] is True

    assert "2026/0042" in client.get(f"/documents/{doc['id']}/pages/1/text").text
    img = client.get(f"/documents/{doc['id']}/pages/1/image")
    assert img.headers["content-type"] == "image/png" and img.content.startswith(b"\x89PNG")
    layout = client.get(f"/documents/{doc['id']}/pages/1/layout").json()
    assert layout["words"] and "bbox" in layout["words"][0]

    m = client.get(f"/documents/{doc['id']}/manifest").json()
    assert m["document"]["sha256"] == doc["sha256"]
    assert len(m["pages"]) == 2 and m["observations"] == []
    # Az eredeti érintetlen.
    assert client.get(f"/documents/{doc['id']}/original").content == invoice_pdf


def test_duplicate_upload_is_not_processed_twice(client, invoice_pdf):
    a = _upload(client, invoice_pdf, "a.pdf")
    b = client.post("/documents", files={"file": ("masik_nev.pdf", invoice_pdf, "application/pdf")})
    assert b.status_code == 200
    assert b.json()["duplicate"] is True and b.json()["id"] == a["id"]
    assert client.get("/documents").json()["total"] == 1


def test_bad_upload_rejected(client):
    r = client.post("/documents", files={"file": ("x.pdf", b"nem pdf", "application/pdf")})
    assert r.status_code == 422
    assert "Nem támogatott" in r.json()["detail"]


def test_resume_skips_done_steps(app, client, settings, invoice_pdf, monkeypatch):
    """Hiba a 2. lépésben: újrafuttatáskor az 1. lépés nem fut újra."""
    doc = _upload(client, invoice_pdf)
    calls = {"split": 0, "extract": 0}
    real_split, real_extract = pl.step_split_pages, pl.step_extract_text

    def split(ctx):
        calls["split"] += 1
        return real_split(ctx)

    def failing_extract(ctx):
        calls["extract"] += 1
        raise RuntimeError("szimulált leállás")

    pipeline = [pl.Step("split_pages", split), pl.Step("extract_text", failing_extract), pl.Step("build_manifest", pl.step_build_manifest)]
    db, storage = app.state.db, app.state.storage

    assert pl.run_document(db, doc["id"], storage, settings, pipeline) == DocStatus.QUEUED
    with db.session() as s:
        steps = {j.name: j for j in s.scalars(select(JobStep).where(JobStep.document_id == doc["id"]))}
        assert steps["split_pages"].status == StepStatus.DONE
        assert steps["extract_text"].status == StepStatus.FAILED
        assert "szimulált" in steps["extract_text"].error

    def extract(ctx):
        calls["extract"] += 1
        return real_extract(ctx)

    pipeline[1] = pl.Step("extract_text", extract)
    assert pl.run_document(db, doc["id"], storage, settings, pipeline) == DocStatus.DONE
    assert calls == {"split": 1, "extract": 2}


def test_gives_up_after_max_attempts_then_retry_endpoint(app, client, settings, invoice_pdf, monkeypatch):
    doc = _upload(client, invoice_pdf)

    def boom(ctx):
        raise RuntimeError("mindig hibás")

    monkeypatch.setattr(pl, "PIPELINE", [pl.Step("split_pages", boom)])
    db, storage = app.state.db, app.state.storage
    statuses = [pl.run_document(db, doc["id"], storage, settings, pl.PIPELINE) for _ in range(settings.max_step_attempts)]
    assert statuses[-1] == DocStatus.FAILED
    d = client.get(f"/documents/{doc['id']}").json()
    assert d["status"] == "failed" and "mindig hibás" in d["error"]

    r = client.post(f"/documents/{doc['id']}/retry")
    assert r.status_code == 200 and r.json()["status"] == "queued"
    monkeypatch.undo()
    assert drain(db, storage, settings) == 1
    assert client.get(f"/documents/{doc['id']}").json()["status"] == "done"


def test_crashed_worker_lock_is_reclaimed(app, client, settings, invoice_pdf):
    """Leállt feldolgozó: a 'processing' irat a zár lejárta után újra felvehető."""
    from datetime import datetime, timedelta, timezone

    from docminer.queue import claim_next

    doc = _upload(client, invoice_pdf)
    db = app.state.db
    assert claim_next(db, "w1") == doc["id"]
    assert claim_next(db, "w2") is None  # friss zár: más nem veheti fel
    with db.session() as s:
        s.get(Document, doc["id"]).locked_at = datetime.now(timezone.utc) - timedelta(hours=2)
    assert claim_next(db, "w2") == doc["id"]


def test_split_is_idempotent(app, client, settings, invoice_pdf):
    doc = _upload(client, invoice_pdf)
    db, storage = app.state.db, app.state.storage
    with db.session() as s:
        d = s.get(Document, doc["id"])
        ctx = pl.StepContext(session=s, doc=d, storage=storage, settings=settings)
        pl.step_split_pages(ctx)
    with db.session() as s:
        d = s.get(Document, doc["id"])
        pl.step_split_pages(pl.StepContext(session=s, doc=d, storage=storage, settings=settings))
    with db.session() as s:
        assert len(s.scalars(select(Page).where(Page.document_id == doc["id"])).all()) == 2


def test_list_filter(client, invoice_pdf):
    from .conftest import make_pdf

    _upload(client, invoice_pdf, "szamla_1.pdf")
    _upload(client, make_pdf(["Szerzodes"]), "szerzodes.pdf")
    assert client.get("/documents", params={"q": "szerz"}).json()["total"] == 1
    assert client.get("/documents", params={"status": "queued"}).json()["total"] == 2


def test_pipeline_overview(app, client, settings, invoice_pdf):
    from .conftest import make_pdf

    done = _upload(client, invoice_pdf, "kesz.pdf")
    drain(app.state.db, app.state.storage, settings)
    waiting = _upload(client, make_pdf(["Varakozo irat szovege itt"]), "var.pdf")

    ov = client.get("/pipeline").json()
    assert ov["documents"]["total"] == 2
    assert ov["documents"]["by_status"] == {"queued": 1, "processing": 0, "done": 1, "failed": 0}

    stages = {s["key"]: s for s in ov["stages"]}
    assert list(stages)[0] == "intake" and list(stages)[-1] == "review"
    assert stages["intake"]["counts"]["done"] == 2
    assert stages["extract_text"]["counts"] == {"pending": 1, "running": 0, "done": 1, "failed": 0}
    assert stages["docsorter"]["implemented"] is True
    assert stages["type_review"]["counts"]["pending"] == 1  # a kész irat típusa jóváhagyásra vár

    items = {i["id"]: i for i in ov["items"]}
    assert items[done["id"]]["stages"]["build_manifest"]["status"] == "done"
    assert items[done["id"]]["scanned_pages"] == [2]
    assert items[waiting["id"]]["stages"]["split_pages"]["status"] == "pending"
    assert items[waiting["id"]]["stages"]["visual"]["status"] == "planned"
