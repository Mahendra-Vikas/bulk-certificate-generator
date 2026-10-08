"""Shared FastAPI dependencies.

The services are created once in ``create_app`` and stored on ``app.state``;
these functions are the typed accessors routes use to reach them. Nothing is
imported at module scope, so a test can build an application with its own
database and storage directory and get fully isolated objects.
"""

from __future__ import annotations

from fastapi import Request

from app.services.certificate_service import CertificateService
from app.services.job_service import JobService


def get_certificate_service(request: Request) -> CertificateService:
    """The process-wide certificate service."""
    return request.app.state.certificate_service


def get_job_service(request: Request) -> JobService:
    """The process-wide job service."""
    return request.app.state.job_service
