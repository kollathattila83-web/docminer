"""Google Document AI OCR (EU-helyszín).

Oldalanként egy egyoldalas PDF-et küld (az azonnali hívás 15 oldalig engedett,
így a határ sosem gond). A visszakapott koordináták 0–1 közöttiek; ezeket az
oldal PDF-pontjaira váltjuk, így ugyanabban a rendszerben vannak, mint a PyMuPDF-é.

Beállítás: `GOOGLE_CLOUD_PROJECT`, `DOCMINER_DOCAI_PROCESSOR_ID`, a hely a
models.yaml `location` mezője (alap: "eu"). Belépés: Application Default Credentials.
"""

from __future__ import annotations

import os

from .base import ModelCallError, OcrPageInput, OcrResult, OcrWord

DEFAULT_LOCATION = "eu"


class DocumentAIOcrProvider:
    name = "document_ai"

    def __init__(self, project: str | None = None, processor_id: str | None = None, client_factory=None) -> None:
        self._project = project
        self._processor_id = processor_id
        self._client_factory = client_factory
        self._clients: dict[str, object] = {}

    def _processor_name(self, location: str) -> str:
        project = self._project or os.environ.get("GOOGLE_CLOUD_PROJECT")
        proc = self._processor_id or os.environ.get("DOCMINER_DOCAI_PROCESSOR_ID")
        if not project or not proc:
            raise ModelCallError(
                "A Document AI nincs beállítva (GOOGLE_CLOUD_PROJECT és DOCMINER_DOCAI_PROCESSOR_ID kell)."
            )
        return f"projects/{project}/locations/{location}/processors/{proc}"

    def _client(self, location: str):
        if location not in self._clients:
            if self._client_factory:
                self._clients[location] = self._client_factory(location)
            else:
                from google.api_core.client_options import ClientOptions
                from google.cloud import documentai

                self._clients[location] = documentai.DocumentProcessorServiceClient(
                    client_options=ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
                )
        return self._clients[location]

    def ocr(self, page: OcrPageInput, spec) -> OcrResult:
        location = spec.location or DEFAULT_LOCATION
        name = self._processor_name(location)
        try:
            from google.cloud import documentai

            request = documentai.ProcessRequest(
                name=name,
                raw_document=documentai.RawDocument(content=page.pdf_bytes, mime_type="application/pdf"),
            )
            result = self._client(location).process_document(request=request)
        except ModelCallError:
            raise
        except Exception as exc:
            raise ModelCallError(f"Document AI hívás sikertelen: {type(exc).__name__}: {exc}") from exc
        return parse_document(result.document, page, model=spec.model, provider=self.name)


def _anchor_text(full: str, layout) -> str:
    segs = getattr(getattr(layout, "text_anchor", None), "text_segments", None) or []
    return "".join(full[int(s.start_index or 0) : int(s.end_index)] for s in segs)


def _bbox(layout, width: float, height: float) -> list[float]:
    verts = list(getattr(layout.bounding_poly, "normalized_vertices", None) or [])
    if not verts:
        return [0.0, 0.0, 0.0, 0.0]
    xs, ys = [v.x for v in verts], [v.y for v in verts]
    return [round(min(xs) * width, 2), round(min(ys) * height, 2), round(max(xs) * width, 2), round(max(ys) * height, 2)]


def parse_document(document, page: OcrPageInput, *, model: str, provider: str = "document_ai") -> OcrResult:
    """A Document AI válaszából szöveg és szavak (tokenek) koordinátával."""
    full = document.text or ""
    words: list[OcrWord] = []
    confs: list[float] = []
    for p in document.pages:
        for t in p.tokens:
            txt = _anchor_text(full, t.layout).strip()
            if not txt:
                continue
            conf = getattr(t.layout, "confidence", None)
            words.append(OcrWord(text=txt, bbox=_bbox(t.layout, page.width, page.height), confidence=conf))
            if conf is not None:
                confs.append(float(conf))
    version = None
    rev = getattr(document, "revisions", None)
    if rev:
        version = getattr(rev[0], "processor", None) or None
    return OcrResult(
        text=full,
        words=words,
        provider=provider,
        model=model,
        model_version=version,
        confidence=round(sum(confs) / len(confs), 4) if confs else None,
        usage={"pages": 1},
    )
