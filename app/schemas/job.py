"""Pydantic schemas for bulk generation jobs.

Validation happens here, before any request reaches the rendering layer:
structurally invalid input is rejected with HTTP 422, while anything that only
fails at generation time becomes a failed *certificate record* instead
(see ``app.services.certificate_service``).
"""

from __future__ import annotations

from datetime import date as DateType
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.db.models import JobStatus

#: Safety limit so one request cannot queue an unbounded amount of work.
MAX_RECIPIENTS_PER_JOB = 1000


class RecipientIn(BaseModel):
    """One person that should receive a certificate."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(..., min_length=1, max_length=120, description="Recipient full name")
    email: Optional[EmailStr] = Field(
        default=None, description="Optional contact email; validated when supplied"
    )
    course: str = Field(
        ..., min_length=1, max_length=160, description="Course or programme name"
    )

    @field_validator("name", "course")
    @classmethod
    def _collapse_whitespace(cls, value: str) -> str:
        """Trim and collapse internal whitespace; reject blank values."""
        collapsed = " ".join(value.split())
        if not collapsed:
            raise ValueError("must not be empty or whitespace only")
        return collapsed

    @field_validator("email", mode="before")
    @classmethod
    def _blank_email_is_none(cls, value: object) -> object:
        """Treat ``""`` and ``"   "`` as "no email" rather than an invalid one."""
        if isinstance(value, str) and not value.strip():
            return None
        return value


class JobCreateRequest(BaseModel):
    """Body of ``POST /api/v1/jobs``."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    event_name: str = Field(
        ..., min_length=1, max_length=200, description="Event or workshop name"
    )
    date: DateType = Field(..., description="Date the event took place (YYYY-MM-DD)")
    recipients: List[RecipientIn] = Field(
        ...,
        min_length=1,
        max_length=MAX_RECIPIENTS_PER_JOB,
        description="At least one recipient is required",
    )

    @field_validator("event_name")
    @classmethod
    def _collapse_event_name(cls, value: str) -> str:
        collapsed = " ".join(value.split())
        if not collapsed:
            raise ValueError("must not be empty or whitespace only")
        return collapsed


class JobCreateResponse(BaseModel):
    """Response of ``POST /api/v1/jobs`` - returned before generation starts."""

    job_id: str
    status: JobStatus
    total: int
    completed: int
    failed: int


class JobStatusResponse(BaseModel):
    """Response of ``GET /api/v1/jobs/{job_id}`` - live progress from the database."""

    job_id: str
    status: JobStatus
    total: int
    completed: int
    failed: int
    pending: int
    progress_percentage: float
    event_name: str
    event_date: DateType
    created_at: datetime
    completed_at: Optional[datetime] = None
