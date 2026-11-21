"""Szolgáltatók nyilvántartása és a lépésenkénti hívás tartalékmodellel."""

from __future__ import annotations

import logging

from ..model_config import ModelConfig
from .base import ModelCallError, OcrPageInput, OcrProvider, OcrResult, Provider, ProviderRequest, ProviderResult, SchemaValidationError, validate_schema
from .document_ai import DocumentAIOcrProvider
from .fake import FakeOcrProvider, FakeProvider
from .vertex_gemini import VertexGeminiProvider

log = logging.getLogger(__name__)


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, Provider | OcrProvider] = {}

    def register(self, provider: Provider | OcrProvider) -> None:
        self._providers[provider.name] = provider

    def get(self, name: str):
        try:
            return self._providers[name]
        except KeyError:
            raise KeyError(
                f"Ismeretlen szolgáltató: '{name}'. Regisztrált: {sorted(self._providers)}"
            ) from None

    def names(self) -> list[str]:
        return sorted(self._providers)


def default_registry() -> ProviderRegistry:
    reg = ProviderRegistry()
    reg.register(FakeProvider())
    reg.register(FakeOcrProvider())
    # A valódi szolgáltatók csak hívásukkor töltik be a Google SDK-t és a belépést.
    reg.register(VertexGeminiProvider())
    reg.register(DocumentAIOcrProvider())
    # Később: AnthropicProvider (második olvasó)
    return reg


def call_step(
    step: str, request: ProviderRequest, config: ModelConfig, registry: ProviderRegistry
) -> ProviderResult:
    """A lépés modelljének hívása. Érvénytelen kimenetnél újrapróbál, majd tartalékra vált.

    Minden sikertelen próbálkozás bekerül az eredmény `attempts` listájába.
    """
    spec = config.for_step(step)
    failures: list[dict] = []
    for candidate in spec.chain():
        provider = registry.get(candidate.provider)
        for attempt in range(1 + config.max_retries):
            try:
                result = provider.generate(request, candidate)
                validate_schema(result.data, request.schema)
            except (ModelCallError, SchemaValidationError) as exc:
                failures.append(
                    {
                        "provider": candidate.provider,
                        "model": candidate.model,
                        "attempt": attempt + 1,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                log.warning("Lépés %s, %s/%s sikertelen: %s", step, candidate.provider, candidate.model, exc)
                continue
            result.attempts = failures
            return result
    raise ModelCallError(f"Lépés '{step}': minden modell sikertelen: {failures}")


def call_ocr(step: str, page: OcrPageInput, config: ModelConfig, registry: ProviderRegistry) -> OcrResult:
    """OCR-hívás a lépés modelljével; hibánál újrapróbál, majd a tartalékra vált."""
    spec = config.for_step(step)
    failures: list[dict] = []
    for candidate in spec.chain():
        provider = registry.get(candidate.provider)
        if not hasattr(provider, "ocr"):
            raise KeyError(f"A(z) '{candidate.provider}' szolgáltató nem OCR-szolgáltató.")
        for attempt in range(1 + config.max_retries):
            try:
                return provider.ocr(page, candidate)
            except ModelCallError as exc:
                failures.append({"provider": candidate.provider, "model": candidate.model, "attempt": attempt + 1, "error": str(exc)})
                log.warning("OCR %s. oldal, %s/%s sikertelen: %s", page.number, candidate.provider, candidate.model, exc)
    raise ModelCallError(f"OCR, {page.number}. oldal: minden próbálkozás sikertelen: {failures}")
