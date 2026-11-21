import json

import pytest

from docminer import pipeline as pl
from docminer.providers import ProviderRegistry
from docminer.providers.fake import FakeProvider
from docminer.worker import drain

from .conftest import make_pdf


def _upload(client, data, name="irat.pdf"):
    r = client.post("/documents", files={"file": (name, data, "application/pdf")})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _run_with(app, settings, doc_id, *responses):
    fake = FakeProvider()
    fake.queue("classify", *responses)
    reg = ProviderRegistry()
    reg.register(fake)
    assert pl.run_document(app.state.db, doc_id, app.state.storage, settings, registry=reg) == "done"
    return fake


def test_classify_step_stores_suggestion_and_waits_for_human(app, client, settings, invoice_pdf):
    doc = _upload(client, invoice_pdf)
    fake = _run_with(app, settings, doc["id"], {"doc_type": "szamla", "confidence": 0.93, "reason": "Számlaszám és ÁFA szerepel."})

    req, _model = fake.calls[0]
    assert req.task == "classify"
    assert "szamla" in req.instructions and "egyeb" in req.instructions
    assert req.schema["properties"]["doc_type"]["enum"][0] == "egyeb"
    assert "2026/0042" in req.pages[0].text
    assert req.pages[1].text is None and req.pages[1].image_path  # szkennelt oldal: kép megy

    d = client.get(f"/documents/{doc['id']}").json()
    assert d["suggested_type"] == "szamla" and d["suggested_confidence"] == 0.93
    assert d["type_status"] == "suggested" and d["doc_type"] is None  # ember még nem döntött
    classify = next(s for s in d["steps"] if s["name"] == "classify")
    assert classify["output"]["provider"] == "fake"

    m = client.get(f"/documents/{doc['id']}/manifest").json()
    assert m["classification"]["suggested"]["doc_type"] == "szamla"
    assert m["classification"]["status"] == "suggested"


def test_default_fake_suggests_other_with_zero_confidence(app, client, settings, invoice_pdf):
    doc = _upload(client, invoice_pdf)
    drain(app.state.db, app.state.storage, settings)
    d = client.get(f"/documents/{doc['id']}").json()
    assert d["suggested_type"] == "egyeb" and d["suggested_confidence"] == 0.0


def test_confidence_is_clamped(app, client, settings, invoice_pdf):
    doc = _upload(client, invoice_pdf)
    _run_with(app, settings, doc["id"], {"doc_type": "szamla", "confidence": 7})
    assert client.get(f"/documents/{doc['id']}").json()["suggested_confidence"] == 1.0


def test_review_queue_approve_and_correct(app, client, settings, invoice_pdf):
    a = _upload(client, invoice_pdf, "a.pdf")
    b = _upload(client, make_pdf(["MEGHATALMAZAS  Alulirott meghatalmazom"]), "b.pdf")
    _run_with(app, settings, a["id"], {"doc_type": "szamla", "confidence": 0.9})
    _run_with(app, settings, b["id"], {"doc_type": "szerzodes", "confidence": 0.4})

    q = client.get("/review/doctypes").json()
    assert q["total"] == 2
    assert [i["id"] for i in q["items"]] == [b["id"], a["id"]]  # a legbizonytalanabb elöl
    assert q["choices"]["egyeb"] and q["choices"]["szamla"] == "Számla"

    r = client.post(f"/documents/{a['id']}/doctype", json={"doc_type": "szamla", "reviewer": "Attila"})
    assert r.status_code == 200 and r.json()["type_status"] == "approved" and r.json()["doc_type"] == "szamla"
    r = client.post(f"/documents/{b['id']}/doctype", json={"doc_type": "meghatalmazas"})
    assert r.json()["type_status"] == "corrected" and r.json()["suggested_type"] == "szerzodes"

    assert client.get("/review/doctypes").json()["total"] == 0
    assert client.get("/review/doctypes", params={"status": "corrected"}).json()["total"] == 1
    assert client.get("/review/doctypes/stats").json() == {"suggested": 0, "approved": 1, "corrected": 1, "accuracy": 0.5}

    m = client.get(f"/documents/{b['id']}/manifest").json()
    assert m["classification"]["doc_type"] == "meghatalmazas" and m["classification"]["status"] == "corrected"

    lines = client.get("/training/doctype.jsonl").text.strip().split("\n")
    rows = {r["document_id"]: r for r in map(json.loads, lines)}
    assert rows[a["id"]]["label"] == "szamla" and rows[a["id"]]["reviewed_by"] == "Attila"
    assert rows[b["id"]]["label"] == "meghatalmazas" and rows[b["id"]]["suggested"] == "szerzodes"
    assert "MEGHATALMAZAS" in rows[b["id"]]["pages"][0]["text"]

    ov = client.get("/pipeline").json()
    stage = next(s for s in ov["stages"] if s["key"] == "type_review")
    assert stage["counts"]["done"] == 2 and stage["counts"]["pending"] == 0


def test_decision_can_be_changed_and_overwrites_example(app, client, settings, invoice_pdf):
    doc = _upload(client, invoice_pdf)
    _run_with(app, settings, doc["id"], {"doc_type": "szamla", "confidence": 0.8})
    client.post(f"/documents/{doc['id']}/doctype", json={"doc_type": "szerzodes"})
    client.post(f"/documents/{doc['id']}/doctype", json={"doc_type": "szamla"})
    rows = client.get("/training/doctype.jsonl").text.strip().split("\n")
    assert len(rows) == 1 and json.loads(rows[0])["label"] == "szamla"


@pytest.mark.parametrize("payload,code", [({"doc_type": "nincs_ilyen"}, 422), ({}, 422)])
def test_invalid_decision_rejected(app, client, settings, invoice_pdf, payload, code):
    doc = _upload(client, invoice_pdf)
    _run_with(app, settings, doc["id"], {"doc_type": "szamla", "confidence": 0.8})
    assert client.post(f"/documents/{doc['id']}/doctype", json=payload).status_code == code


def test_decision_before_suggestion_rejected(client, invoice_pdf):
    doc = _upload(client, invoice_pdf)  # még nem futott le
    assert client.post(f"/documents/{doc['id']}/doctype", json={"doc_type": "szamla"}).status_code == 409
