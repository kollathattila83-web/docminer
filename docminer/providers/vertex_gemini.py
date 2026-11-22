"""Gemini a Vertex AI-on (alapból az EU-végponton).

Belépés: Application Default Credentials (`gcloud auth application-default login`),
így kulcsot nem kell sehová bemásolni. A projektet a `GOOGLE_CLOUD_PROJECT`
környezeti változó adja, a helyet a models.yaml `location` mezője (pl. "eu").

A kimenet a kérés JSON-sémájához kötött (strukturált kimenet), a sémát a hívó
réteg (`call_step`) még egyszer ellenőrzi.
"""

from __future__ import annotations

import os
from pathlib import Path

from .base import ModelCallError, ProviderRequest, ProviderResult

DEFAULT_LOCATION = "eu"


class VertexGeminiProvider:
    name = "vertex_gemini"

    def __init__(self, project: str | None = None, client_factory=None) -> None:
        self._project = project
        self._client_factory = client_factory  # tesztekhez
        self._clients: dict[str, object] = {}

    @property
    def project(self) -> str:
        p = self._project or os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not p:
            raise ModelCallError("Nincs megadva a Google Cloud projekt (GOOGLE_CLOUD_PROJECT).")
        return p

    def _client(self, location: str):
        if location not in self._clients:
            if self._client_factory:
                self._clients[location] = self._client_factory(location)
            else:
                from google import genai  # lusta import: csak akkor kell, ha ezt a szolgáltatót használjuk

                self._clients[location] = genai.Client(vertexai=True, project=self.project, location=location)
        return self._clients[location]

    @staticmethod
    def _contents(request: ProviderRequest, send_images: bool) -> list:
        from google.genai import types

        parts: list = []
        for p in request.pages:
            parts.append(types.Part.from_text(text=f"--- {p.number}. oldal ---\n{p.text or '(nincs szövegréteg)'}"))
            if send_images and p.image_path:
                parts.append(types.Part.from_bytes(data=Path(p.image_path).read_bytes(), mime_type="image/png"))
        return [types.Content(role="user", parts=parts)]

    def generate(self, request: ProviderRequest, spec) -> ProviderResult:
        from google.genai import errors, types

        location = spec.location or DEFAULT_LOCATION
        params = dict(spec.params)
        send_images = bool(params.pop("send_images", False))
        config = types.GenerateContentConfig(
            system_instruction=request.instructions,
            response_mime_type="application/json",
            response_json_schema=request.schema,
            temperature=params.pop("temperature", 0.0),
            max_output_tokens=params.pop("max_output_tokens", 2048),
            **({"thinking_config": types.ThinkingConfig(thinking_level=spec.reasoning)} if spec.reasoning else {}),
            **params,
        )
        try:
            resp = self._client(location).models.generate_content(
                model=spec.model, contents=self._contents(request, send_images), config=config
            )
        except errors.APIError as exc:
            raise ModelCallError(f"Vertex AI hiba ({getattr(exc, 'code', '?')}): {exc}") from exc
        except Exception as exc:  # hálózati vagy belépési hiba
            raise ModelCallError(f"Vertex AI hívás sikertelen: {type(exc).__name__}: {exc}") from exc

        data = resp.parsed if isinstance(resp.parsed, dict) else None
        if data is None:
            import json

            try:
                data = json.loads(resp.text or "")
            except (ValueError, TypeError) as exc:
                raise ModelCallError(f"A modell válasza nem JSON: {(resp.text or '')[:200]!r}") from exc
        um = resp.usage_metadata
        return ProviderResult(
            data=data,
            provider=self.name,
            model=spec.model,
            model_version=getattr(resp, "model_version", None),
            usage={
                "input_tokens": getattr(um, "prompt_token_count", None),
                "output_tokens": getattr(um, "candidates_token_count", None),
                "thinking_tokens": getattr(um, "thoughts_token_count", None),
                "pages": len(request.pages),
                "location": location,
            },
        )
