"""Hamis szolgáltató tesztekhez és helyi fejlesztéshez: nem hív hálózatot, nem kerül pénzbe.

Előre megadott válaszokat ad vissza feladatonként; ha nincs ilyen, a sémából
üres (null értékű) kimenetet épít. Hibát és érvénytelen kimenetet is tud szimulálni.
"""

from __future__ import annotations

from collections import defaultdict, deque

from .base import ModelCallError, OcrPageInput, OcrResult, OcrWord, ProviderRequest, ProviderResult


def empty_from_schema(schema: dict):
    if schema.get("enum"):
        return schema["enum"][0]
    t = schema.get("type")
    t = t[0] if isinstance(t, list) else t
    if t == "object":
        req = set(schema.get("required", []))
        return {k: empty_from_schema(s) for k, s in schema.get("properties", {}).items() if k in req}
    if t == "array":
        return []
    if t == "boolean":
        return False
    if t in ("integer", "number"):
        return 0
    if isinstance(schema.get("type"), list) and "null" in schema["type"]:
        return None
    return ""


class FakeProvider:
    name = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[ProviderRequest, str]] = []
        # (modell, feladat) -> válaszok sora; "*" bármely modellre illeszkedik
        self._queue: dict[tuple[str, str], deque] = defaultdict(deque)

    def queue(self, task: str, *responses, model: str = "*") -> None:
        """Válasz(ok) előkészítése. Egy válasz lehet dict vagy Exception példány."""
        self._queue[(model, task)].extend(responses)

    def _next(self, model: str, task: str):
        for key in ((model, task), ("*", task)):
            if self._queue[key]:
                return self._queue[key].popleft()
        return None

    def generate(self, request: ProviderRequest, spec) -> ProviderResult:
        self.calls.append((request, spec.model))
        resp = self._next(spec.model, request.task)
        if isinstance(resp, Exception):
            raise resp if isinstance(resp, ModelCallError) else ModelCallError(str(resp))
        data = resp if resp is not None else empty_from_schema(request.schema)
        chars = sum(len(p.text or "") for p in request.pages)
        return ProviderResult(
            data=data,
            provider=self.name,
            model=spec.model,
            model_version="fake-1",
            usage={"input_tokens": chars // 4, "output_tokens": 0, "pages": len(request.pages), "cost_usd": 0.0},
        )


class FakeOcrProvider:
    """Hamis OCR: előre megadott szöveget ad oldalanként (alapból egy rövid mintát)."""

    name = "fake_ocr"

    def __init__(self) -> None:
        self.calls: list[int] = []
        self.texts: dict[int, str] = {}
        self.fail_pages: set[int] = set()

    def ocr(self, page: OcrPageInput, spec) -> OcrResult:
        self.calls.append(page.number)
        if page.number in self.fail_pages:
            raise ModelCallError(f"szimulált OCR-hiba a(z) {page.number}. oldalon")
        text = self.texts.get(page.number, f"OCR minta szöveg {page.number}. oldal")
        words, x = [], 72.0
        for w in text.split():
            words.append(OcrWord(text=w, bbox=[x, 72.0, x + 6 * len(w), 84.0], confidence=0.99))
            x += 6 * len(w) + 4
        return OcrResult(text=text, words=words, provider=self.name, model=spec.model, model_version="fake-1",
                         confidence=0.99 if words else None, usage={"pages": 1})
