"""Persistence: projects, uploaded files, supplier catalogues and an audit log.

Pipeline outputs are stored as JSON documents on the project row; the shape
is owned by the pipeline modules, so the schema stays small for the pilot.
Tables are created on startup (no migrations yet).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, LargeBinary, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from safetyplan.config import settings


def _id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    owner: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    inputs: Mapped[dict] = mapped_column(JSON, default=dict)  # ProjectInputs
    instructions_text: Mapped[str] = mapped_column(Text, default="")
    instructions: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # ParsedInstructions
    instructions_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)

    plan_file: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {name, ref, kind, calibration}
    geometry: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    detection: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # DetectionResult
    review: Mapped[dict] = mapped_column(JSON, default=dict)  # {types, protected_edges, added}
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # ProjectPlan
    result_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    selected_supplier: Mapped[str | None] = mapped_column(String(64), nullable=True)
    photo_checks: Mapped[list] = mapped_column(JSON, default=list)

    def summary(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "has_plan": self.plan_file is not None,
            "has_result": self.result is not None,
        }


class StoredFile(Base):
    """Small uploads (< 4.5 MB) kept in the database; large ones live in Vercel Blob."""

    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    owner: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SupplierRow(Base):
    __tablename__ = "suppliers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(200))
    data: Mapped[dict] = mapped_column(JSON)  # catalog.model.Supplier
    import_errors: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditEvent(Base):
    __tablename__ = "audit"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    actor: Mapped[str] = mapped_column(String(128))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)

    def to_dict(self) -> dict:
        return {"at": self.at.isoformat(), "actor": self.actor, "action": self.action, "detail": self.detail}


@lru_cache(maxsize=None)
def _sessionmaker(url: str) -> sessionmaker:
    kw = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
    engine = create_engine(url, **kw)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def get_session() -> Session:
    return _sessionmaker(settings().database_url)()
