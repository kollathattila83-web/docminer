"""Adatmodell: irat, oldal, lépésállapot.

Minden irat minden lépése külön sort kap (JobStep), így leállás után a feldolgozás
onnan folytatható, és a már lefutott (akár kifizetett) lépés nem fut újra.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return uuid.uuid4().hex


class DocStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class TypeStatus(StrEnum):
    """Az irattípus állapota. A gép javasol, ember dönt."""

    SUGGESTED = "suggested"  # a DocSorter javasolta, emberi jóváhagyásra vár
    APPROVED = "approved"  # az ember elfogadta a javaslatot
    CORRECTED = "corrected"  # az ember más típust választott


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    filename: Mapped[str] = mapped_column(String(512))
    mime: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=DocStatus.QUEUED, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Ki dolgozik rajta éppen (worker azonosító), és mióta.
    locked_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Irattípus: a DocSorter javaslata és az ember döntése külön mezőben, hogy mérhető legyen a pontosság.
    suggested_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    suggested_confidence: Mapped[float | None] = mapped_column(nullable=True)
    suggested_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    doc_type: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    type_status: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    pages: Mapped[list[Page]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="Page.number"
    )
    steps: Mapped[list[JobStep]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="JobStep.order"
    )


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("document_id", "number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer)  # 1-től
    width: Mapped[float] = mapped_column()
    height: Mapped[float] = mapped_column()
    image_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # "digital" = van szövegréteg, "scanned" = OCR kell (később Document AI)
    kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    document: Mapped[Document] = relationship(back_populates="pages")


class JobStep(Base):
    __tablename__ = "job_steps"
    __table_args__ = (UniqueConstraint("document_id", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(50))
    order: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default=StepStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A lépés kimenetének összefoglalója és a használt modell/eszköz (nyomon követhetőség).
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped[Document] = relationship(back_populates="steps")


class UsageRecord(Base):
    """Szolgáltatói felhasználás naplója (oldal, token) a havi korlátokhoz és a költségméréshez."""

    __tablename__ = "usage_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    month: Mapped[str] = mapped_column(String(7), index=True)  # "2026-11"
    step: Mapped[str] = mapped_column(String(50))
    provider: Mapped[str] = mapped_column(String(50), index=True)
    model: Mapped[str] = mapped_column(String(100))
    document_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
