"""Havi felhasználási korlát a fizetős MI-hívásokra.

A Google költségkerete a legtöbb szolgáltatásnál csak figyelmeztet; ez az őr a
hívás előtt ellenőrzi a havi hívás- és tokenszámot, és túllépésnél megállít.
A próbaszolgáltatók (`fake*`) nem számítanak bele. Minden valódi hívás saját
tranzakcióban kerül a naplóba, így hiba esetén sem vész el a már kifizetett hívás.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select

from .db import Database
from .models import UsageRecord
from .providers.base import BudgetExceeded, ProviderResult
from .settings import Settings


def current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def is_billable(provider: str) -> bool:
    return not provider.startswith("fake")


@dataclass
class UsageGuard:
    db: Database
    settings: Settings
    document_id: str | None = None
    step: str = ""

    def llm_usage(self, month: str | None = None) -> tuple[int, int]:
        """(hívások, tokenek) a hónapban, a valódi modellszolgáltatóknál (OCR nélkül)."""
        month = month or current_month()
        with self.db.session() as s:
            calls, tokens = s.execute(
                select(
                    func.count(UsageRecord.id),
                    func.coalesce(func.sum(UsageRecord.input_tokens + UsageRecord.output_tokens), 0),
                ).where(
                    UsageRecord.month == month,
                    UsageRecord.step != "ocr",
                    ~UsageRecord.provider.startswith("fake"),
                )
            ).one()
        return int(calls), int(tokens)

    def check(self, provider: str) -> None:
        if not is_billable(provider):
            return
        calls, tokens = self.llm_usage()
        st = self.settings
        if calls >= st.llm_monthly_call_limit:
            raise BudgetExceeded(
                f"Havi modellhívás-korlát elfogyott: {calls} / {st.llm_monthly_call_limit} hívás "
                "(DOCMINER_LLM_MONTHLY_CALL_LIMIT)."
            )
        if tokens >= st.llm_monthly_token_limit:
            raise BudgetExceeded(
                f"Havi tokenkorlát elfogyott: {tokens} / {st.llm_monthly_token_limit} token "
                "(DOCMINER_LLM_MONTHLY_TOKEN_LIMIT)."
            )

    def record(self, step: str, result: ProviderResult) -> None:
        u = result.usage or {}
        thinking = int(u.get("thinking_tokens") or 0)  # a gondolkodási token is kimenetként fizetendő
        with self.db.session() as s:
            s.add(
                UsageRecord(
                    month=current_month(),
                    step=step or self.step,
                    provider=result.provider,
                    model=result.model,
                    document_id=self.document_id,
                    pages=int(u.get("pages") or 0),
                    input_tokens=int(u.get("input_tokens") or 0),
                    output_tokens=int(u.get("output_tokens") or 0) + thinking,
                )
            )
