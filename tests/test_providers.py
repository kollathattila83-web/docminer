import pytest

from docminer.model_config import ModelConfig
from docminer.providers import (
    ModelCallError,
    PageInput,
    Provider,
    ProviderRequest,
    call_step,
    default_registry,
)
from docminer.providers.fake import FakeProvider

SCHEMA = {
    "type": "object",
    "properties": {"doctype": {"type": "string", "enum": ["szamla", "szerzodes", "ismeretlen"]}, "confidence": {"type": "number"}},
    "required": ["doctype"],
}


def _config(**over):
    return ModelConfig.model_validate(
        {
            "max_retries": over.get("max_retries", 1),
            "steps": {
                "docsorter": {
                    "provider": "fake",
                    "model": "primary",
                    "fallback": {"provider": "fake", "model": "backup"},
                }
            },
        }
    )


def _req():
    return ProviderRequest(task="classify", instructions="Sorold be.", schema=SCHEMA, pages=[PageInput(1, text="SZÁMLA ...")])


def _registry():
    reg = default_registry()
    return reg, reg.get("fake")


def test_fake_satisfies_protocol():
    assert isinstance(FakeProvider(), Provider)


def test_success_records_model_for_traceability():
    reg, fake = _registry()
    fake.queue("classify", {"doctype": "szamla", "confidence": 0.9})
    res = call_step("docsorter", _req(), _config(), reg)
    assert res.data["doctype"] == "szamla"
    assert res.trace()["model"] == "primary" and res.trace()["provider"] == "fake"
    assert res.attempts == []


def test_invalid_output_retries_then_falls_back():
    reg, fake = _registry()
    fake.queue("classify", {"doctype": "kenyer"}, {"nincs": "doctype"}, model="primary")
    fake.queue("classify", {"doctype": "szerzodes"}, model="backup")
    res = call_step("docsorter", _req(), _config(max_retries=1), reg)
    assert res.model == "backup" and res.data["doctype"] == "szerzodes"
    assert [a["model"] for a in res.attempts] == ["primary", "primary"]
    assert [m for _, m in fake.calls] == ["primary", "primary", "backup"]


def test_provider_error_falls_back():
    reg, fake = _registry()
    fake.queue("classify", ModelCallError("429 kvóta"), model="primary")
    fake.queue("classify", {"doctype": "szamla"}, model="backup")
    res = call_step("docsorter", _req(), _config(max_retries=0), reg)
    assert res.model == "backup"
    assert "429" in res.attempts[0]["error"]


def test_all_fail_raises():
    reg, fake = _registry()
    fake.queue("classify", {"x": 1}, {"x": 1}, {"x": 1}, {"x": 1})
    with pytest.raises(ModelCallError, match="minden modell sikertelen"):
        call_step("docsorter", _req(), _config(), reg)


def test_unknown_provider_and_step():
    reg, _ = _registry()
    cfg = ModelConfig.model_validate({"steps": {"docsorter": {"provider": "nincs_ilyen", "model": "m"}}})
    with pytest.raises(KeyError, match="Ismeretlen szolgáltató"):
        call_step("docsorter", _req(), cfg, reg)
    with pytest.raises(KeyError, match="Nincs modellbeállítás"):
        call_step("extraction", _req(), cfg, reg)


def test_swapping_model_is_config_only():
    reg, fake = _registry()
    cfg = _config()
    cfg.steps["docsorter"].model = "uj-modell"
    res = call_step("docsorter", _req(), cfg, reg)
    assert res.model == "uj-modell"
