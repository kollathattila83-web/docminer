"""Irattípusok YAML-ból. Új típushoz új fájl kell, nem új kód.

A típusfájlból készül a modellnek adott JSON-séma: minden mező egy megfigyelés
(érték + oldal + bbox + bizonyosság), így bármely modell ugyanazt tölti ki.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

FieldType = Literal["string", "date", "money", "number", "tax_id", "company_reg_no", "iban", "enum", "party", "text"]

_JSON_TYPE = {
    "string": "string",
    "date": "string",
    "money": "number",
    "number": "number",
    "tax_id": "string",
    "company_reg_no": "string",
    "iban": "string",
    "enum": "string",
    "text": "string",
}


class FieldDef(BaseModel):
    key: str
    label: str
    type: FieldType = "string"
    required: bool = False
    multiple: bool = False
    # Csalási pont (bankszámla, adószám): mindig második ellenőrzést kap.
    verify: bool = False
    values: list[str] | None = None  # enum esetén
    description: str | None = None


class VisualDef(BaseModel):
    key: str
    label: str
    per_party: bool = False
    per_page: bool = False


class DocType(BaseModel):
    id: str
    name: str
    description: str = ""
    version: int = 1
    fields: list[FieldDef]
    visual_elements: list[VisualDef] = Field(default_factory=list)

    @field_validator("fields")
    @classmethod
    def _unique_keys(cls, v: list[FieldDef]) -> list[FieldDef]:
        keys = [f.key for f in v]
        dup = {k for k in keys if keys.count(k) > 1}
        if dup:
            raise ValueError(f"Ismétlődő mezőkulcs: {sorted(dup)}")
        return v

    def field(self, key: str) -> FieldDef:
        return next(f for f in self.fields if f.key == key)

    def json_schema(self) -> dict:
        """A modelltől várt kimenet sémája (modellfüggetlen)."""
        props = {}
        for f in self.fields:
            obs = _observation_schema(f)
            props[f.key] = {"type": "array", "items": obs} if f.multiple else obs
        visual = {
            v.key: {"type": "array", "items": _visual_schema()} for v in self.visual_elements
        }
        return {
            "type": "object",
            "properties": {
                "fields": {"type": "object", "properties": props, "required": [f.key for f in self.fields if f.required]},
                "visual_elements": {"type": "object", "properties": visual},
            },
            "required": ["fields"],
        }


def _observation_schema(f: FieldDef) -> dict:
    if f.type == "party":
        value: dict = {
            "type": ["object", "null"],
            "properties": {
                "name": {"type": "string"},
                "tax_id": {"type": ["string", "null"]},
                "company_reg_no": {"type": ["string", "null"]},
                "representative": {"type": ["string", "null"]},
                "address": {"type": ["string", "null"]},
            },
            "required": ["name"],
        }
    else:
        value = {"type": [_JSON_TYPE[f.type], "null"]}
        if f.type == "enum" and f.values:
            value["enum"] = [*f.values, None]
    return {
        "type": "object",
        "properties": {
            "value": value,
            "page": {"type": ["integer", "null"]},
            "bbox": {"type": ["array", "null"], "items": {"type": "number"}},
            "confidence": {"type": ["number", "null"]},
        },
        "required": ["value"],
    }


def _visual_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "present": {"type": "boolean"},
            "page": {"type": "integer"},
            "bbox": {"type": "array", "items": {"type": "number"}},
            "party": {"type": ["string", "null"]},
            "confidence": {"type": ["number", "null"]},
        },
        "required": ["present", "page"],
    }


def load_doctype(path: Path) -> DocType:
    with open(path, encoding="utf-8") as fh:
        return DocType.model_validate(yaml.safe_load(fh))


def load_doctypes(directory: Path) -> dict[str, DocType]:
    out: dict[str, DocType] = {}
    for p in sorted(Path(directory).glob("*.yaml")):
        dt = load_doctype(p)
        if dt.id in out:
            raise ValueError(f"Ismétlődő irattípus-azonosító: {dt.id} ({p.name})")
        out[dt.id] = dt
    return out
