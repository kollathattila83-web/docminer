import pytest
import yaml

from docminer.doctypes import DocType, load_doctypes
from docminer.model_config import load_model_config
from docminer.providers import validate_schema
from docminer.providers.fake import empty_from_schema

from .conftest import CONFIG_DIR


def test_three_doctypes_load():
    types = load_doctypes(CONFIG_DIR / "doctypes")
    assert set(types) == {"szamla", "szerzodes", "meghatalmazas"}
    szamla = types["szamla"]
    assert szamla.field("bankszamlaszam").verify is True
    assert szamla.field("elado_adoszam").verify is True
    assert [v.key for v in types["szerzodes"].visual_elements] == ["alairas", "belyegzo", "kezirasos_kiegeszites", "szigno"]
    assert types["meghatalmazas"].field("tanuk").multiple is True


def test_doctype_schema_accepts_observation_and_rejects_bad_type():
    szamla = load_doctypes(CONFIG_DIR / "doctypes")["szamla"]
    schema = szamla.json_schema()
    good = {
        "fields": {
            "szamlaszam": {"value": "2026/0042", "page": 1, "bbox": [72, 60, 140, 75], "confidence": 0.98},
            "kelte": {"value": "2026-11-10"},
            "elado_nev": {"value": "Minta Kft."},
            "vevo_nev": {"value": "Vevő Bt."},
            "brutto": {"value": 127000},
            "fizetesi_mod": {"value": "atutalas"},
        },
        "visual_elements": {"belyegzo": [{"present": True, "page": 1, "bbox": [400, 700, 520, 800]}]},
    }
    validate_schema(good, schema)
    bad = {"fields": {**good["fields"], "brutto": {"value": "százhuszonhétezer"}}}
    with pytest.raises(ValueError, match="brutto"):
        validate_schema(bad, schema)
    with pytest.raises(ValueError, match="nem megengedett"):
        validate_schema({"fields": {**good["fields"], "fizetesi_mod": {"value": "csekk"}}}, schema)
    with pytest.raises(ValueError, match="szamlaszam"):
        validate_schema({"fields": {k: v for k, v in good["fields"].items() if k != "szamlaszam"}}, schema)


def test_empty_output_from_schema_is_valid_shape():
    for dt in load_doctypes(CONFIG_DIR / "doctypes").values():
        schema = dt.json_schema()
        empty = empty_from_schema(schema)
        assert set(empty["fields"]) == {f.key for f in dt.fields if f.required}


def test_duplicate_field_keys_rejected():
    with pytest.raises(ValueError, match="Ismétlődő"):
        DocType.model_validate({"id": "x", "name": "X", "fields": [{"key": "a", "label": "A"}, {"key": "a", "label": "B"}]})


def test_new_doctype_is_just_a_file(tmp_path):
    (tmp_path / "szallitolevel.yaml").write_text(
        yaml.safe_dump({"id": "szallitolevel", "name": "Szállítólevél", "fields": [{"key": "szam", "label": "Szám", "required": True}]}),
        encoding="utf-8",
    )
    assert "szallitolevel" in load_doctypes(tmp_path)


def test_model_config_every_step_has_model():
    cfg = load_model_config(CONFIG_DIR / "models.yaml")
    for step in ["docsorter", "ocr", "extraction", "visual", "second_reader", "doubt_checker"]:
        spec = cfg.for_step(step)
        assert spec.provider and spec.model
    assert [s.model for s in cfg.for_step("extraction").chain()] == ["fake-extractor", "fake-extractor-backup"]


def test_config_endpoints(client):
    assert "szamla" in client.get("/config/doctypes").json()
    assert client.get("/config/models").json()["steps"]["docsorter"]["provider"] == "fake"
    assert client.get("/health").json()["status"] == "ok"
