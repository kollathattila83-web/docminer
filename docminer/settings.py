"""Futási beállítások környezeti változókból (nincs külön függőség)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.environ.get(
            "DOCMINER_DATABASE_URL", f"sqlite:///{_ROOT / 'data' / 'docminer.db'}"
        )
    )
    data_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("DOCMINER_DATA_DIR", _ROOT / "data"))
    )
    config_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("DOCMINER_CONFIG_DIR", _ROOT / "config"))
    )
    max_upload_mb: int = field(
        default_factory=lambda: int(os.environ.get("DOCMINER_MAX_UPLOAD_MB", "100"))
    )
    max_pages: int = field(
        default_factory=lambda: int(os.environ.get("DOCMINER_MAX_PAGES", "2000"))
    )
    render_dpi: int = field(
        default_factory=lambda: int(os.environ.get("DOCMINER_RENDER_DPI", "150"))
    )
    worker_poll_seconds: float = field(
        default_factory=lambda: float(os.environ.get("DOCMINER_WORKER_POLL_SECONDS", "2"))
    )
    # Modellprofil a config mappán belül (pl. models.google.yaml a valódi szolgáltatókhoz).
    models_file: str = field(default_factory=lambda: os.environ.get("DOCMINER_MODELS_FILE", "models.yaml"))
    # Havi OCR-oldalkorlát a valódi (nem fake) szolgáltatóknál. A Google költségkerete csak
    # figyelmeztet, ez tényleg megállít. Alap: a Document AI ingyenes havi 1 000 oldala.
    ocr_monthly_page_limit: int = field(
        default_factory=lambda: int(os.environ.get("DOCMINER_OCR_MONTHLY_PAGE_LIMIT", "1000"))
    )
    # Havi korlát a valódi modellhívásokra (Gemini stb.); túllépésnél a feldolgozás megáll.
    llm_monthly_call_limit: int = field(
        default_factory=lambda: int(os.environ.get("DOCMINER_LLM_MONTHLY_CALL_LIMIT", "2000"))
    )
    llm_monthly_token_limit: int = field(
        default_factory=lambda: int(os.environ.get("DOCMINER_LLM_MONTHLY_TOKEN_LIMIT", "5000000"))
    )
    # OCR-hez küldött oldal felbontása, ha az eredeti kép (nem PDF).
    ocr_image_dpi: int = field(default_factory=lambda: int(os.environ.get("DOCMINER_OCR_IMAGE_DPI", "300")))
    # Ennyi próbálkozás után a lépés végleg hibás (failed) marad.
    max_step_attempts: int = field(
        default_factory=lambda: int(os.environ.get("DOCMINER_MAX_STEP_ATTEMPTS", "3"))
    )
    # A DocSorter-nek ennyi karaktert küldünk oldalanként, és legfeljebb ennyi oldalt.
    classify_max_pages: int = field(
        default_factory=lambda: int(os.environ.get("DOCMINER_CLASSIFY_MAX_PAGES", "3"))
    )
    classify_chars_per_page: int = field(
        default_factory=lambda: int(os.environ.get("DOCMINER_CLASSIFY_CHARS_PER_PAGE", "4000"))
    )


def models_path(settings: Settings) -> Path:
    return settings.config_dir / settings.models_file


def get_settings() -> Settings:
    return Settings()
