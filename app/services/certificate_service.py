"""Certificate persistence and file access.

This module owns everything about a *single* certificate: its ID, its database
row, and the PDF on disk. Bulk orchestration lives in
``app.services.job_service``; drawing lives in
``app.services.rendering_service``.

Nothing here knows about HTTP, and nothing here returns a filesystem path to a
caller that might forward it to a client - ``download()`` hands back an open
file object plus the name it should be served as.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import BinaryIO, Dict, List, NamedTuple, Optional

from sqlalchemy import func, select

from app.db.models import Certificate, CertificateStatus, GenerationJob
from app.db.database import Database
from app.services.rendering_service import (
    CertificateContent,
    CertificateRenderer,
    CertificateRenderingError,
)
from app.utils.file_utils import certificate_pdf_path, download_url

logger = logging.getLogger(__name__)

#: ``CERT-<year>-<sequence>``; kept in sync with
#: ``app.utils.file_utils.CERTIFICATE_ID_PATTERN``.
ID_PREFIX = "CERT"
SEQUENCE_DIGITS = 6
MAX_SEQUENCE = 10**SEQUENCE_DIGITS - 1

#: How many times a colliding ID is regenerated before giving up. With six
#: digits per year a collision only happens on a real race, so a couple of
#: retries is plenty.
MAX_ID_ATTEMPTS = 5


class CertificateNotFound(LookupError):
    """Raised when a certificate ID is unknown or its PDF is unavailable."""


class FileDownload(NamedTuple):
    """A readable PDF and the filename it should be served under."""

    stream: BinaryIO
    filename: str
    content_type: str


def generate_certificate_id(sequence: int, year: Optional[int] = None) -> str:
    """Build ``CERT-YYYY-NNNNNN`` for *sequence* (1-based) in *year*.

    Raises:
        ValueError: if the sequence has grown past what six digits can hold.
    """
    if not 1 <= sequence <= MAX_SEQUENCE:
        raise ValueError(f"Certificate sequence out of range: {sequence}")
    resolved_year = year if year is not None else datetime.now(timezone.utc).year
    return f"{ID_PREFIX}-{resolved_year:04d}-{sequence:0{SEQUENCE_DIGITS}d}"


def _utcnow() -> datetime:
    """Naive UTC timestamp, matching the model default."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class CertificateService:
    """Reads and writes certificate rows, and serves their PDFs."""

    def __init__(self, database: Database, renderer: CertificateRenderer) -> None:
        self.database = database
        self.renderer = renderer

    # -- receipts ----------------------------------------------------------
    def create_receipts(
        self,
        job_pk: int,
        recipients: List[Dict[str, str]],
        year: Optional[int] = None,
    ) -> int:
        """Insert one PENDING certificate per recipient and return how many.

        IDs are allocated in this one transaction, so a job's certificates are
        numbered consecutively. Rows are written before any rendering starts,
        which is what lets a client poll for progress instead of waiting for
        the whole job.
        """
        resolved_year = year if year is not None else datetime.now(timezone.utc).year
        with self.database.session_factory() as session:
            highest = session.scalar(
                select(func.max(Certificate.sequence)).where(
                    Certificate.issue_year == resolved_year
                )
            )
            sequence = highest or 0

            for recipient in recipients:
                sequence += 1
                session.add(
                    Certificate(
                        job_id=job_pk,
                        certificate_id=generate_certificate_id(sequence, resolved_year),
                        issue_year=resolved_year,
                        sequence=sequence,
                        recipient_name=recipient["name"],
                        recipient_email=recipient.get("email"),
                        course_name=recipient["course"],
                        status=CertificateStatus.PENDING,
                    )
                )

            session.commit()
        return len(recipients)

    # -- generation --------------------------------------------------------
    def render_certificate(self, certificate_pk: int) -> Path:
        """Render one pending certificate's PDF and mark its row SUCCESS.

        Content is read from the row itself, so a receipt can be re-rendered
        later without keeping the original request around.

        Raises:
            CertificateNotFound: if the row does not exist.
            CertificateRenderingError: if the PDF could not be produced.
        """
        with self.database.session_factory() as session:
            certificate = session.get(Certificate, certificate_pk)
            if certificate is None:
                raise CertificateNotFound(f"Certificate {certificate_pk} not found")
            content = CertificateContent(
                recipient_name=certificate.recipient_name,
                course_name=certificate.course_name,
                event_name=certificate.job.event_name,
                event_date=certificate.job.event_date,
                certificate_id=certificate.certificate_id,
            )
            certificate_id = certificate.certificate_id
            certificate_pk_holder = certificate.id

        # Drawing happens outside the transaction: a slow render must never
        # hold a database lock.
        path = self.renderer.render_to_storage(content)

        with self.database.session_factory() as session:
            certificate = session.get(Certificate, certificate_pk_holder)
            if certificate is not None:  # the row only disappears if the job was deleted
                certificate.status = CertificateStatus.SUCCESS
                certificate.file_path = str(path)
                certificate.error_message = None
                certificate.completed_at = _utcnow()
                session.commit()

        logger.info("Rendered certificate %s", certificate_id)
        return path

    def mark_failed(self, certificate_pk: int, reason: str) -> bool:
        """Record a failed certificate. Returns False if the row is gone."""
        with self.database.session_factory() as session:
            certificate = session.get(Certificate, certificate_pk)
            if certificate is None:
                return False
            certificate.status = CertificateStatus.FAILED
            certificate.error_message = reason
            certificate.file_path = None
            certificate.completed_at = _utcnow()
            session.commit()
        return True

    # -- reads -------------------------------------------------------------
    def get_certificate(self, certificate_id: str) -> Optional[Certificate]:
        """The certificate row with *certificate_id*, if it exists."""
        with self.database.session_factory() as session:
            return session.scalar(
                select(Certificate).where(Certificate.certificate_id == certificate_id)
            )

    def list_certificates(self, job_pk: int) -> List[Certificate]:
        """Every certificate of a job, in issuance order."""
        with self.database.session_factory() as session:
            return list(
                session.scalars(
                    select(Certificate)
                    .where(Certificate.job_id == job_pk)
                    .order_by(Certificate.id)
                )
            )

    def download(self, certificate_id: str) -> FileDownload:
        """Open the rendered PDF for a certificate.

        Raises:
            CertificateNotFound: if the ID is unknown, still generating, failed,
                or its file has since been deleted. The message is client-safe
                and never contains a filesystem path.
        """
        certificate = self.get_certificate(certificate_id)
        if certificate is None:
            raise CertificateNotFound(f"Unknown certificate: {certificate_id}")
        if certificate.status is not CertificateStatus.SUCCESS:
            raise CertificateNotFound(
                f"Certificate {certificate_id} is not available "
                f"(status: {certificate.status.value})"
            )

        # ``certificate_id`` comes from the database, but validating it before
        # it is used as a path segment removes any chance of traversal.
        path = certificate_pdf_path(self.renderer.storage_dir, certificate_id)
        if not path.is_file():
            logger.error("Certificate row %s has no PDF at %s", certificate_id, path)
            raise CertificateNotFound(f"Certificate file missing: {certificate_id}")

        return FileDownload(
            stream=path.open("rb"),
            filename=f"{certificate_id}.pdf",
            content_type="application/pdf",
        )

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def download_url(certificate_id: str) -> str:
        """Relative URL a client can call to fetch the PDF."""
        return download_url(certificate_id)


def certificate_result_payload(certificate: Certificate) -> Dict[str, object]:
    """Shape one certificate row for :class:`app.schemas.certificate.CertificateResult`.

    Only successful certificates advertise a download URL, and the raw
    filesystem path is never exposed.
    """
    succeeded = certificate.status is CertificateStatus.SUCCESS
    return {
        "certificate_id": certificate.certificate_id,
        "recipient_name": certificate.recipient_name,
        "course": certificate.course_name,
        "status": certificate.status,
        "download_url": download_url(certificate.certificate_id) if succeeded else None,
        "error": certificate.error_message,
    }
