"""OCR-lépés és a Google-adapterek (hálózat nélkül, hamis kliensekkel)."""

import json
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import select

from docminer import pipeline as pl
from docminer.model_config import ModelSpec
from docminer.models import Document, DocStatus, JobStep, Page, UsageRecord
from docminer.providers import OcrPageInput, ProviderRequest, default_registry
from docminer.providers.base import ModelCallError
from docminer.providers.document_ai import DocumentAIOcrProvider, parse_document
from docminer.providers.vertex_gemini import VertexGeminiProvider
from docminer.storage import LocalStorage
from docminer.worker import drain

from .conftest import make_pdf


def _upload(client, data, name="scan.pdf"):
    r = client.post("/documents", files={"file": (name, data, "application/pdf")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_scanned_pages_get_ocr_text_and_layout(app, client, settings, invoice_pdf):
    doc_id = _upload(client, invoice_pdf)
    reg = default_registry()
    reg.get("fake_ocr").texts[2] = "SZÁMLA 2026/0042 Bruttó 127 000 Ft"
    pl.run_document(app.state.db, doc_id, app.state.storage, settings, registry=reg)

    assert reg.get("fake_ocr").calls == [2]  # csak a szkennelt oldal megy OCR-re
    assert "2026/0042" in client.get(f"/documents/{doc_id}/pages/2/text").text
    layout = client.get(f"/documents/{doc_id}/pages/2/layout").json()
    assert layout["tool"] == "ocr:fake_ocr/fake-ocr"
    assert layout["words"][1]["text"] == "2026/0042" and len(layout["words"][1]["bbox"]) == 4
    d = client.get(f"/documents/{doc_id}").json()
    ocr = next(s for s in d["steps"] if s["name"] == "ocr")
    assert ocr["output"]["ocr_pages"] == 1 and ocr["output"]["avg_confidence"] == 0.99


def test_ocr_resume_does_not_pay_twice(app, client, settings):
    doc_id = _upload(client, make_pdf([None, None, None]))
    reg = default_registry()
    fake = reg.get("fake_ocr")
    fake.fail_pages = {3}
    db, storage = app.state.db, app.state.storage
    # A 3. oldal elbukik; az 1–2. oldal eredménye fájlban megmarad.
    pl.run_document(db, doc_id, storage, settings, registry=reg)
    assert fake.calls == [1, 2, 3, 3]  # max_retries=1
    fake.fail_pages = set()
    assert pl.run_document(db, doc_id, storage, settings, registry=reg) == DocStatus.DONE
    assert fake.calls == [1, 2, 3, 3, 3]  # az 1–2. oldal nem ment újra
    with db.session() as s:
        texts = [p.text for p in s.scalars(select(Page).where(Page.document_id == doc_id).order_by(Page.number))]
        out = s.scalar(select(JobStep).where(JobStep.document_id == doc_id, JobStep.name == "ocr")).output
    assert all(t.startswith("OCR minta") for t in texts)
    assert out["resumed_pages"] == 2 and out["ocr_pages"] == 1


def test_monthly_page_limit_stops_real_provider(app, client, settings, tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    (cfg / "doctypes").mkdir(parents=True)
    (cfg / "models.yaml").write_text(
        "steps:\n  ocr: {provider: document_ai, model: document-ocr, location: eu}\n", encoding="utf-8"
    )
    from dataclasses import replace

    s2 = replace(settings, config_dir=cfg, ocr_monthly_page_limit=2)
    doc_id = _upload(client, make_pdf([None, None, None]))
    with app.state.db.session() as s:
        s.add(UsageRecord(month=pl._month(), step="ocr", provider="document_ai", model="x", pages=1))

    class NeverCalled:
        name = "document_ai"

        def ocr(self, page, spec):  # pragma: no cover
            raise AssertionError("a korlát fölött nem hívhat")

    reg = default_registry()
    reg.register(NeverCalled())
    assert pl.run_document(app.state.db, doc_id, app.state.storage, s2, registry=reg) in (DocStatus.QUEUED, DocStatus.FAILED)
    d = client.get(f"/documents/{doc_id}").json()
    assert "Havi OCR-korlát" in d["error"]


def test_fake_ocr_usage_not_counted_against_limit(app, client, settings):
    doc_id = _upload(client, make_pdf([None]))
    drain(app.state.db, app.state.storage, settings)
    with app.state.db.session() as s:
        assert pl.ocr_pages_used(s, pl._month()) == 0
        assert s.scalar(select(UsageRecord).where(UsageRecord.document_id == doc_id)).provider == "fake_ocr"


# --- Document AI adapter --------------------------------------------------


def _docai_document():
    text = "SZÁMLA\n2026/0042\n"

    def tok(start, end, box, conf):
        x0, y0, x1, y1 = box
        verts = [NS(x=x0, y=y0), NS(x=x1, y=y0), NS(x=x1, y=y1), NS(x=x0, y=y1)]
        return NS(layout=NS(text_anchor=NS(text_segments=[NS(start_index=start, end_index=end)]),
                            bounding_poly=NS(normalized_vertices=verts), confidence=conf))

    return NS(
        text=text,
        pages=[NS(tokens=[tok(0, 7, (0.1, 0.1, 0.3, 0.12), 0.98), tok(7, 17, (0.1, 0.2, 0.4, 0.22), 0.90)])],
        revisions=[],
    )


def test_document_ai_parse_converts_bbox_to_points():
    page = OcrPageInput(number=1, width=600.0, height=800.0, pdf_bytes=b"")
    res = parse_document(_docai_document(), page, model="document-ocr")
    assert [w.text for w in res.words] == ["SZÁMLA", "2026/0042"]
    assert res.words[0].bbox == [60.0, 80.0, 180.0, 96.0]
    assert res.confidence == 0.94


def test_document_ai_adapter_uses_eu_processor(monkeypatch):
    seen = {}

    class Client:
        def process_document(self, request):
            seen["name"] = request.name
            seen["mime"] = request.raw_document.mime_type
            return NS(document=_docai_document())

    def factory(location):
        seen["location"] = location
        return Client()

    prov = DocumentAIOcrProvider(project="docminer-123", processor_id="abc123", client_factory=factory)
    res = prov.ocr(OcrPageInput(1, 600, 800, b"%PDF-1.7"), ModelSpec(provider="document_ai", model="document-ocr", location="eu"))
    assert seen == {"location": "eu", "name": "projects/docminer-123/locations/eu/processors/abc123", "mime": "application/pdf"}
    assert res.text.startswith("SZÁMLA")


def test_document_ai_missing_config_is_clear(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("DOCMINER_DOCAI_PROCESSOR_ID", raising=False)
    with pytest.raises(ModelCallError, match="nincs beállítva"):
        DocumentAIOcrProvider().ocr(OcrPageInput(1, 1, 1, b""), ModelSpec(provider="document_ai", model="m"))


# --- Vertex AI Gemini adapter ---------------------------------------------


class _FakeModels:
    def __init__(self, response=None, exc=None):
        self.response, self.exc, self.calls = response, exc, []

    def generate_content(self, model, contents, config):
        self.calls.append((model, contents, config))
        if self.exc:
            raise self.exc
        return self.response


def _gemini(models):
    seen = {}

    def factory(location):
        seen["location"] = location
        return NS(models=models)

    return VertexGeminiProvider(project="docminer-123", client_factory=factory), seen


SCHEMA = {"type": "object", "properties": {"doc_type": {"type": "string"}}, "required": ["doc_type"]}


def test_gemini_structured_output_and_usage():
    resp = NS(parsed={"doc_type": "szamla"}, text='{"doc_type": "szamla"}', model_version="gemini-3.8-flash-001",
              usage_metadata=NS(prompt_token_count=1500, candidates_token_count=20, thoughts_token_count=0))
    models = _FakeModels(resp)
    prov, seen = _gemini(models)
    req = ProviderRequest(task="classify", instructions="Sorold be.", schema=SCHEMA,
                          pages=[__import__("docminer.providers", fromlist=["PageInput"]).PageInput(1, text="SZÁMLA")])
    res = prov.generate(req, ModelSpec(provider="vertex_gemini", model="gemini-3.8-flash", location="eu", reasoning="low"))
    assert seen["location"] == "eu"
    assert res.data == {"doc_type": "szamla"} and res.model_version == "gemini-3.8-flash-001"
    assert res.usage["input_tokens"] == 1500
    model, contents, config = models.calls[0]
    assert model == "gemini-3.8-flash"
    assert config.response_mime_type == "application/json" and config.response_json_schema == SCHEMA
    assert config.system_instruction == "Sorold be."
    assert "SZÁMLA" in contents[0].parts[0].text


def test_gemini_falls_back_to_text_json_and_wraps_errors():
    resp = NS(parsed=None, text='{"doc_type": "egyeb"}', model_version=None, usage_metadata=None)
    prov, _ = _gemini(_FakeModels(resp))
    req = ProviderRequest(task="classify", instructions="x", schema=SCHEMA)
    assert prov.generate(req, ModelSpec(provider="vertex_gemini", model="m")).data == {"doc_type": "egyeb"}

    prov, _ = _gemini(_FakeModels(NS(parsed=None, text="nem json", model_version=None, usage_metadata=None)))
    with pytest.raises(ModelCallError, match="nem JSON"):
        prov.generate(req, ModelSpec(provider="vertex_gemini", model="m"))

    prov, _ = _gemini(_FakeModels(exc=ConnectionError("nincs hálózat")))
    with pytest.raises(ModelCallError, match="nincs hálózat"):
        prov.generate(req, ModelSpec(provider="vertex_gemini", model="m"))


def test_google_profile_loads():
    from docminer.model_config import load_model_config

    from .conftest import CONFIG_DIR

    cfg = load_model_config(CONFIG_DIR / "models.google.yaml")
    assert cfg.for_step("ocr").provider == "document_ai" and cfg.for_step("ocr").location == "eu"
    assert cfg.for_step("docsorter").provider == "vertex_gemini" and cfg.for_step("docsorter").location == "eu"
    assert set(default_registry().names()) >= {"document_ai", "vertex_gemini", "fake", "fake_ocr"}


# --- Havi modellhívás-korlát ---------------------------------------------


def _guarded(app, settings, **limits):
    from dataclasses import replace

    from docminer.budget import UsageGuard

    reg = default_registry()
    st = replace(settings, **limits)
    reg.guard = UsageGuard(app.state.db, st, document_id=None, step="docsorter")
    return reg, st


class _PaidModel:
    name = "vertex_gemini"

    def __init__(self):
        self.calls = 0

    def generate(self, request, spec):
        from docminer.providers import ProviderResult

        self.calls += 1
        return ProviderResult(data={"doc_type": "szamla"}, provider=self.name, model=spec.model,
                              usage={"input_tokens": 1000, "output_tokens": 50, "thinking_tokens": 10, "pages": 1})


def _cfg():
    from docminer.model_config import ModelConfig

    return ModelConfig.model_validate({"steps": {"docsorter": {"provider": "vertex_gemini", "model": "gemini-3.8-flash",
                                                               "fallback": {"provider": "vertex_gemini", "model": "masik"}}}})


def test_llm_call_limit_stops_before_paid_call(app, settings):
    from docminer.providers import BudgetExceeded, call_step

    reg, _ = _guarded(app, settings, llm_monthly_call_limit=2)
    paid = _PaidModel()
    reg.register(paid)
    req = ProviderRequest(task="classify", instructions="x", schema=SCHEMA)
    call_step("docsorter", req, _cfg(), reg)
    call_step("docsorter", req, _cfg(), reg)
    with pytest.raises(BudgetExceeded, match="modellhívás-korlát"):
        call_step("docsorter", req, _cfg(), reg)
    assert paid.calls == 2  # a harmadik hívás el sem indult, és tartalékra sem váltott
    with app.state.db.session() as s:
        recs = s.scalars(select(UsageRecord).where(UsageRecord.step == "docsorter")).all()
    assert [(r.input_tokens, r.output_tokens) for r in recs] == [(1000, 60), (1000, 60)]


def test_llm_token_limit(app, settings):
    from docminer.providers import BudgetExceeded, call_step

    reg, _ = _guarded(app, settings, llm_monthly_token_limit=1500)
    reg.register(_PaidModel())
    req = ProviderRequest(task="classify", instructions="x", schema=SCHEMA)
    call_step("docsorter", req, _cfg(), reg)  # 1060 token
    call_step("docsorter", req, _cfg(), reg)  # még a korlát alatt indult: 2120
    with pytest.raises(BudgetExceeded, match="tokenkorlát"):
        call_step("docsorter", req, _cfg(), reg)


def test_fake_provider_ignores_llm_limit(app, settings):
    from docminer.model_config import ModelConfig
    from docminer.providers import call_step

    reg, _ = _guarded(app, settings, llm_monthly_call_limit=0)
    cfg = ModelConfig.model_validate({"steps": {"docsorter": {"provider": "fake", "model": "f"}}})
    call_step("docsorter", ProviderRequest(task="classify", instructions="x", schema=SCHEMA), cfg, reg)


def test_budget_exceeded_fails_document_immediately(app, client, settings):
    from docminer.providers import BudgetExceeded

    doc_id = _upload(client, make_pdf(["Valami digitalis szoveg itt van"]))

    def broke(ctx):
        raise BudgetExceeded("Havi modellhívás-korlát elfogyott")

    steps = [pl.Step("split_pages", pl.step_split_pages), pl.Step("classify", broke)]
    assert pl.run_document(app.state.db, doc_id, app.state.storage, settings, steps) == DocStatus.FAILED
    with app.state.db.session() as s:
        assert s.scalar(select(JobStep).where(JobStep.document_id == doc_id, JobStep.name == "classify")).attempts == 1


def test_usage_endpoint(client):
    u = client.get("/usage").json()
    assert u["ocr_pages"] == {"used": 0, "limit": 1000}
    assert u["llm_calls"]["limit"] == 2000 and u["models_file"] == "models.yaml"
