"""Bulk generation jobs: creation, background processing and progress reads.

A job is created *immediately* and processed by a daemon thread, so the HTTP
request that submits 1000 recipients returns in milliseconds. The client polls
``GET /api/v1/jobs/{job_id}`` for progress; the database is the single source of
truth, which means progress survives a page reload and is correct even if the
process is restarted mid-job.

Failure isolation is deliberate: one recipient that cannot be rendered (a name
Pillow refuses to draw, a disk hiccup) is recorded as a failed certificate and
the remaining recipients are still processed.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import func, select, update

from app.db.database import Database
from app.db.models import Certificate, CertificateStatus, GenerationJob, JobStatus
from app.services.certificate_service import CertificateService
from app.services.rendering_service import CertificateRenderingError

logger = logging.getLogger(__name__)

#: Job IDs are unguessable but readable: ``job_<32 hex chars>``.
JOB_ID_PREFIX = "job_"

#: Fallback text stored with a certificate whose failure raised without a message.
GENERIC_FAILURE = "Certificate could not be generated"


class JobNotFound(LookupError):
    """Raised when a job ID does not exist."""


class JobService:
    """Creates bulk jobs and advances them in the background."""

    def __init__(self, database: Database, certificates: CertificateService) -> None:
        self.database = database
        self.certificates = certificates
        # Guards the bookkeeping below; the actual work runs in threads, so the
        # collections are only touched while holding it.
        self._lock = threading.Lock()
        self._threads: Dict[str, threading.Thread] = {}

    # -- creation ----------------------------------------------------------
    def create_job(
        self,
        event_name: str,
        event_date: date,
        recipients: List[Dict[str, str]],
    ) -> str:
        """Persist a new job with one PENDING certificate per recipient.

        Returns the public ``job_id`` as soon as the rows are committed; the
        rendering thread starts immediately afterwards.
        """
        job_id = f"{JOB_ID_PREFIX}{uuid.uuid4().hex}"
        total = len(recipients)

        with self.database.session_factory() as session:
            job = GenerationJob(
                job_id=job_id,
                event_name=event_name,
                event_date=event_date,
                status=JobStatus.PENDING,
                total_count=total,
                success_count=0,
                failed_count=0,
            )
            session.add(job)
            session.commit()
            job_pk = job.id

        # Receipts are written before the thread starts so that a client that
        # polls the moment it receives the job_id always sees its recipients.
        self.certificates.create_receipts(job_pk, recipients)
        self._start_worker(job_id, job_pk)
        return job_id

    def _start_worker(self, job_id: str, job_pk: int) -> None:
        """Run ``_process_job`` on a daemon thread.

        Daemon threads keep Ctrl-C responsive and never block interpreter
        shutdown; a job interrupted that way is finalised as failed on the next
        process that reads it, because its certificates are already persisted.
        """
        thread = threading.Thread(
            target=self._process_job,
            args=(job_id, job_pk),
            name=f"certificate-job-{job_id}",
            daemon=True,
        )
        with self._lock:
            # Drop finished threads as we go, so a long-lived process does not
            # accumulate one entry per job ever created.
            stale = [key for key, value in self._threads.items() if not value.is_alive()]
            for key in stale:
                self._threads.pop(key, None)
            self._threads[job_id] = thread
        thread.start()

    # -- processing --------------------------------------------------------
    def _process_job(self, job_id: str, job_pk: int) -> None:
        """Render every certificate of a job, then mark the job terminal."""
        try:
            self._set_status(job_pk, JobStatus.PROCESSING)

            with self.database.session_factory() as session:
                certificate_pks = list(
                    session.scalars(
                        select(Certificate.id)
                        .where(Certificate.job_id == job_pk)
                        .order_by(Certificate.id)
                    )
                )

            for certificate_pk in certificate_pks:
                self._render_one(job_pk, certificate_pk)

            self._finish(job_pk)
        except Exception as exc:  # noqa: BLE001 - the job must never die silently
            logger.exception("Job %s failed unexpectedly", job_id)
            self._fail_job(job_pk, exc)

    def _render_one(self, job_pk: int, certificate_pk: int) -> None:
        """Render one certificate, recording success or failure, then count it.

        The counters are recomputed from the rows rather than incremented, so
        they stay correct no matter how a certificate ended up in its state.
        """
        try:
            self.certificates.render_certificate(certificate_pk)
        except CertificateRenderingError as exc:
            # Expected failure: the message is written for the client to read.
            self.certificates.mark_failed(certificate_pk, str(exc))
        except Exception as exc:  # noqa: BLE001 - anything else is still per-recipient
            logger.exception("Unexpected error rendering certificate %s", certificate_pk)
            self.certificates.mark_failed(certificate_pk, GENERIC_FAILURE)

        self._refresh_counts(job_pk)

    def _refresh_counts(self, job_pk: int) -> None:
        """Copy per-status totals onto the job row."""
        with self.database.session_factory() as session:
            counts = dict(
                session.execute(
                    select(Certificate.status, func.count(Certificate.id))
                    .where(Certificate.job_id == job_pk)
                    .group_by(Certificate.status)
                ).all()
            )
            job = session.get(GenerationJob, job_pk)
            if job is None:  # pragma: no cover - only if deleted mid-job
                return
            job.success_count = counts.get(CertificateStatus.SUCCESS, 0)
            job.failed_count = counts.get(CertificateStatus.FAILED, 0)
            session.commit()

    def _finish(self, job_pk: int) -> None:
        """Mark a fully processed job COMPLETED or COMPLETED_WITH_ERRORS."""
        with self.database.session_factory() as session:
            job = session.get(GenerationJob, job_pk)
            if job is None:  # pragma: no cover - only if deleted mid-job
                return

            pending = (
                session.scalar(
                    select(func.count(Certificate.id)).where(
                        Certificate.job_id == job_pk,
                        Certificate.status == CertificateStatus.PENDING,
                    )
                )
                or 0
            )
            if pending:
                # Should not happen in a clean run; recording them as failed is
                # what guarantees every job eventually reaches a terminal state.
                logger.warning("Job %s finished with %s unprocessed receipts", job.job_id, pending)
                session.execute(
                    update(Certificate)
                    .where(
                        Certificate.job_id == job_pk,
                        Certificate.status == CertificateStatus.PENDING,
                    )
                    .values(
                        status=CertificateStatus.FAILED,
                        error_message=GENERIC_FAILURE,
                        completed_at=_utcnow(),
                    )
                )

            counts = dict(
                session.execute(
                    select(Certificate.status, func.count(Certificate.id))
                    .where(Certificate.job_id == job_pk)
                    .group_by(Certificate.status)
                ).all()
            )
            job.success_count = counts.get(CertificateStatus.SUCCESS, 0)
            job.failed_count = counts.get(CertificateStatus.FAILED, 0)

            if job.failed_count == 0:
                job.status = JobStatus.COMPLETED
            elif job.success_count > 0:
                job.status = JobStatus.COMPLETED_WITH_ERRORS
            else:
                job.status = JobStatus.FAILED
            job.completed_at = _utcnow()
            session.commit()

        logger.info("Job %s finished", job_pk)

    def _set_status(self, job_pk: int, status: JobStatus) -> None:
        with self.database.session_factory() as session:
            job = session.get(GenerationJob, job_pk)
            if job is not None:
                job.status = status
                session.commit()

    def _fail_job(self, job_pk: int, exc: Exception) -> None:
        """Terminal state for a job that blew up outside per-certificate handling."""
        with self.database.session_factory() as session:
            job = session.get(GenerationJob, job_pk)
            if job is None:  # pragma: no cover - only if deleted mid-job
                return
            job.status = JobStatus.FAILED
            job.error_message = f"Job failed: {type(exc).__name__}: {exc}"
            job.completed_at = _utcnow()
            session.commit()

    # -- reads -------------------------------------------------------------
    def get_job(self, job_id: str) -> GenerationJob:
        """The job row for *job_id*.

        Raises:
            JobNotFound: if no such job exists.
        """
        with self.database.session_factory() as session:
            job = session.scalar(select(GenerationJob).where(GenerationJob.job_id == job_id))
            if job is None:
                raise JobNotFound(f"Unknown job: {job_id}")
            return job

    def list_certificates(self, job_pk: int) -> List[Certificate]:
        """Every certificate of a job, in issuance order."""
        return self.certificates.list_certificates(job_pk)

    def is_running(self, job_id: str) -> bool:
        """True while this process still has a worker thread for *job_id*."""
        with self._lock:
            thread = self._threads.get(job_id)
        return bool(thread and thread.is_alive())


def _utcnow() -> datetime:
    """Naive UTC timestamp, matching the model default."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
