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


def get_settings() -> Settings:
    return Settings()
