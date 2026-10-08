"""SQLAlchemy models: one row per generation job, one row per certificate."""

from __future__ import annotations

import enum
from datetime import date, datetime, timezone
from typing import List, Optional

from sqlalchemy import Date, DateTime, Enum as SAEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Naive UTC timestamp.

    SQLite has no timezone-aware type, so timestamps are stored as naive UTC
    values to keep reads and writes symmetric.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    """Declarative base for every table in the application."""


class JobStatus(str, enum.Enum):
    """Lifecycle of a bulk generation job."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    FAILED = "FAILED"


class CertificateStatus(str, enum.Enum):
    """Lifecycle of a single certificate inside a job."""

    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


def _enum_column(enum_cls: type[enum.Enum], length: int = 32) -> SAEnum:
    """Store enum *values* (not member names) as short strings."""
    return SAEnum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda cls: [member.value for member in cls],
        validate_strings=True,
    )


class GenerationJob(Base):
    """A single bulk request: one event, many recipients."""

    __tablename__ = "generation_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    event_name: Mapped[str] = mapped_column(String(200), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        _enum_column(JobStatus), default=JobStatus.PENDING, nullable=False
    )
    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    certificates: Mapped[List["Certificate"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Certificate(Base):
    """One recipient's certificate, tracked independently of the rest of the job."""

    __tablename__ = "certificates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("generation_jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    certificate_id: Mapped[str] = mapped_column(
        String(40), unique=True, index=True, nullable=False
    )
    #: Issue year and per-year sequence are stored as numbers rather than parsed
    #: back out of ``certificate_id``, so allocating the next ID is a plain
    #: ``MAX(sequence)`` and can never be confused by an unusual ID value.
    issue_year: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    recipient_name: Mapped[str] = mapped_column(String(120), nullable=False)
    recipient_email: Mapped[Optional[str]] = mapped_column(String(254), nullable=True)
    course_name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[CertificateStatus] = mapped_column(
        _enum_column(CertificateStatus), default=CertificateStatus.PENDING, nullable=False
    )
    file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    job: Mapped[GenerationJob] = relationship(back_populates="certificates")
