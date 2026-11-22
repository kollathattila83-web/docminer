"""Háttérsor az adatbázisban: nincs külön üzenetsor-szolgáltatás.

PostgreSQL-en `FOR UPDATE SKIP LOCKED`, így több feldolgozó is futhat egyszerre
anélkül, hogy ugyanazt az iratot vennék fel. A beragadt (leállt feldolgozó által
fogva tartott) irat a zárolás lejárta után újra felvehető, és onnan folytatódik.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select

from .db import Database
from .models import Document, DocStatus

STALE_LOCK = timedelta(minutes=30)


def claim_next(db: Database, worker_id: str, stale_after: timedelta = STALE_LOCK) -> str | None:
    now = datetime.now(timezone.utc)
    with db.session() as s:
        q = (
            select(Document)
            .where(
                or_(
                    Document.status == DocStatus.QUEUED,
                    and_(Document.status == DocStatus.PROCESSING, Document.locked_at < now - stale_after),
                )
            )
            .order_by(Document.created_at)
            .limit(1)
        )
        if db.is_postgres:
            q = q.with_for_update(skip_locked=True)
        doc = s.scalars(q).first()
        if doc is None:
            return None
        doc.status, doc.locked_by, doc.locked_at = DocStatus.PROCESSING, worker_id, now
        return doc.id
