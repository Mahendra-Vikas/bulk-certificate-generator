"""Pydantic schemas describing one certificate in a job."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from app.db.models import CertificateStatus


class CertificateResult(BaseModel):
    """Response item of ``GET /api/v1/jobs/{job_id}/certificates``.

    ``download_url`` is only present for successful certificates, and ``error``
    is only present for failed ones - a client never receives a filesystem path.
    """

    certificate_id: str
    recipient_name: str
    course: str
    status: CertificateStatus
    download_url: Optional[str] = None
    error: Optional[str] = None
