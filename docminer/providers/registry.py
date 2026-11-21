"""Szolgáltatók nyilvántartása és a lépésenkénti hívás tartalékmodellel."""

from __future__ import annotations

import logging

from ..model_config import ModelConfig
from .base import ModelCallError, Provider, ProviderRequest, ProviderResult, SchemaValidationError, validate_schema
from .fake import FakeProvider

log = logging.getLogger(__name__)


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}

    def register(self, provider: Provider) -> None:
        self._providers[provider.name] = provider

    def get(self, name: str) -> Provider:
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
    # Később: VertexGeminiProvider, DocumentAIProvider, AnthropicProvider ...
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
