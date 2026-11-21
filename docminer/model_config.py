"""Lépésenkénti modellbeállítás. A modell beállítás, nem kód: cseréje egy sor a YAML-ban."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ModelSpec(BaseModel):
    provider: str
    model: str
    reasoning: str | None = None  # pl. low / medium / high, ha a szolgáltató támogatja
    location: str | None = None  # pl. "eu" (Vertex AI EU-végpont)
    params: dict = Field(default_factory=dict)
    fallback: ModelSpec | None = None

    def chain(self) -> list[ModelSpec]:
        """Az elsődleges modell, majd a tartalékok sorban."""
        out, cur = [], self
        while cur is not None:
            out.append(cur)
            cur = cur.fallback
        return out


class ModelConfig(BaseModel):
    # Ennyiszer próbálja újra ugyanazt a modellt érvénytelen kimenetnél, mielőtt tartalékra vált.
    max_retries: int = 1
    steps: dict[str, ModelSpec]

    def for_step(self, step: str) -> ModelSpec:
        try:
            return self.steps[step]
        except KeyError:
            raise KeyError(f"Nincs modellbeállítás ehhez a lépéshez: {step}") from None


def load_model_config(path: Path) -> ModelConfig:
    with open(path, encoding="utf-8") as fh:
        return ModelConfig.model_validate(yaml.safe_load(fh))
