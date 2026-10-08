"""Bulk generation job endpoints.

``POST /jobs`` accepts a list of recipients and returns immediately;
``GET /jobs/{job_id}`` reports progress; ``GET /jobs/{job_id}/certificates``
lists per-recipient outcomes with a download link for each success.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_job_service
from app.db.models import CertificateStatus, GenerationJob, JobStatus
from app.schemas.certificate import CertificateResult
from app.schemas.job import JobCreateRequest, JobCreateResponse, JobStatusResponse
from app.services.certificate_service import certificate_result_payload
from app.services.job_service import JobNotFound, JobService

router = APIRouter(prefix="/jobs", tags=["jobs"])

JobServiceDep = Annotated[JobService, Depends(get_job_service)]


def _progress(job: GenerationJob) -> Dict[str, Any]:
    """Counts shared by the status and creation responses."""
    total = job.total_count or 0
    completed = job.success_count or 0
    failed = job.failed_count or 0
    settled = completed + failed

    return {
        "total": total,
        "completed": completed,
        "failed": failed,
        "pending": max(total - settled, 0),
        "progress_percentage": round(settled / total * 100, 2) if total else 0.0,
    }


def _get_job_or_404(jobs: JobService, job_id: str) -> GenerationJob:
    """The job row, or ``404`` for an unknown (or mistyped) job ID."""
    try:
        return jobs.get_job(job_id)
    except JobNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "",
    response_model=JobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a bulk certificate job",
)
def create_job(payload: JobCreateRequest, jobs: JobServiceDep) -> JobCreateResponse:
    """Queue one certificate per recipient and start generating in the background.

    Returns ``202`` with the new ``job_id``; poll ``GET /jobs/{job_id}`` for
    progress. Recipients are validated (and the list is capped) before any work
    is queued, so a malformed request is rejected with ``422`` and never leaves
    a half-built job behind.
    """
    job_id = jobs.create_job(
        event_name=payload.event_name,
        event_date=payload.date,
        recipients=[recipient.model_dump() for recipient in payload.recipients],
    )

    return JobCreateResponse(
        job_id=job_id,
        status=JobStatus.PENDING,
        total=len(payload.recipients),
        completed=0,
        failed=0,
    )


@router.get(
    "/{job_id}",
    response_model=JobStatusResponse,
    summary="Job progress",
)
def get_job(job_id: str, jobs: JobServiceDep) -> JobStatusResponse:
    """Current status and counts, read from the database."""
    job = _get_job_or_404(jobs, job_id)
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        event_name=job.event_name,
        event_date=job.event_date,
        created_at=job.created_at,
        completed_at=job.completed_at,
        **_progress(job),
    )


@router.get(
    "/{job_id}/certificates",
    response_model=List[CertificateResult],
    summary="Per-recipient results",
)
def list_job_certificates(
    job_id: str,
    jobs: JobServiceDep,
    certificate_status: Annotated[
        CertificateStatus | None,
        Query(alias="status", description="Optional filter by certificate status"),
    ] = None,
) -> List[CertificateResult]:
    """Every certificate of the job, successful ones carrying a ``download_url``."""
    job = _get_job_or_404(jobs, job_id)
    certificates = jobs.list_certificates(job.id)

    if certificate_status is not None:
        certificates = [
            certificate
            for certificate in certificates
            if certificate.status is certificate_status
        ]

    return [CertificateResult(**certificate_result_payload(item)) for item in certificates]
