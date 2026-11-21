"""Szolgáltató-interfész és modellfüggetlen kimenet-ellenőrzés.

Új szolgáltató (Vertex AI Gemini, Document AI, Claude, OpenAI, helyi modell)
egyetlen osztály, amely a `Provider` protokollt valósítja meg.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ..model_config import ModelSpec


@dataclass
class PageInput:
    number: int
    text: str | None = None
    image_path: str | None = None  # helyi fájl; az adapter dönti el, hogyan küldi


@dataclass
class ProviderRequest:
    task: str  # pl. "classify", "extract", "visual", "second_read"
    instructions: str
    schema: dict
    pages: list[PageInput] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)  # pl. irattípus, irat-azonosító


@dataclass
class ProviderResult:
    data: dict
    provider: str
    model: str
    model_version: str | None = None
    usage: dict = field(default_factory=dict)  # input_tokens, output_tokens, pages, cost_usd
    attempts: list[dict] = field(default_factory=list)  # sikertelen próbálkozások naplója

    def trace(self) -> dict:
        """A kinyert érték mellé tárolt nyomkövetési adat."""
        return {
            "provider": self.provider,
            "model": self.model,
            "model_version": self.model_version,
            "usage": self.usage,
            "failed_attempts": self.attempts,
        }


@dataclass
class OcrWord:
    text: str
    bbox: list[float]  # PDF-pontban, bal felső sarok az origó (mint a PyMuPDF-nél)
    confidence: float | None = None


@dataclass
class OcrResult:
    """Egy oldal OCR-eredménye. A koordináták az oldal PDF-pontjaiban vannak."""

    text: str
    words: list[OcrWord]
    provider: str
    model: str
    model_version: str | None = None
    confidence: float | None = None  # az oldal átlagos bizonyossága
    usage: dict = field(default_factory=dict)

    def layout(self, number: int, width: float, height: float) -> dict:
        return {
            "page": number,
            "width": width,
            "height": height,
            "kind": "scanned",
            "tool": f"ocr:{self.provider}/{self.model}",
            "model_version": self.model_version,
            "confidence": self.confidence,
            "words": [{"text": w.text, "bbox": w.bbox, "confidence": w.confidence} for w in self.words],
            "blocks": [],
            "tables": [],
        }


@dataclass
class OcrPageInput:
    number: int
    width: float  # PDF-pont
    height: float
    pdf_bytes: bytes  # egyoldalas PDF (az eredeti felbontással)


class ModelCallError(RuntimeError):
    """A szolgáltató hívása sikertelen (hálózat, kvóta, szolgáltatói hiba)."""


class BudgetExceeded(RuntimeError):
    """A havi felhasználási korlát elfogyott. Nem vált tartalékmodellre: a hívás megáll."""


class SchemaValidationError(ValueError):
    pass


@runtime_checkable
class Provider(Protocol):
    name: str

    def generate(self, request: ProviderRequest, spec: ModelSpec) -> ProviderResult: ...


@runtime_checkable
class OcrProvider(Protocol):
    name: str

    def ocr(self, page: OcrPageInput, spec: ModelSpec) -> OcrResult: ...


# --- Minimális JSON-séma ellenőrző (type, properties, required, items, enum) ---
# Szándékosan kicsi, hogy ne kelljen külön függőség; a modellek kimenetéhez elég.

_PY_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "null": (type(None),),
}


def _type_ok(value: Any, t: str) -> bool:
    if t in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, _PY_TYPES[t])


def validate_schema(value: Any, schema: dict, path: str = "$") -> None:
    types = schema.get("type")
    if types is not None:
        tl = [types] if isinstance(types, str) else types
        if not any(_type_ok(value, t) for t in tl):
            raise SchemaValidationError(f"{path}: várt típus {tl}, kapott {type(value).__name__}")
    if "enum" in schema and value not in schema["enum"]:
        raise SchemaValidationError(f"{path}: nem megengedett érték {value!r}")
    if isinstance(value, dict):
        for req in schema.get("required", []):
            if req not in value:
                raise SchemaValidationError(f"{path}: hiányzó kötelező kulcs '{req}'")
        for k, sub in schema.get("properties", {}).items():
            if k in value:
                validate_schema(value[k], sub, f"{path}.{k}")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            validate_schema(item, schema["items"], f"{path}[{i}]")
