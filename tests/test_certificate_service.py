"""Certificate IDs, receipts, rendering and download."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.core.config import Settings
from app.db.database import Database
from app.db.models import Certificate, CertificateStatus, GenerationJob
from app.services.certificate_service import (
    CertificateNotFound,
    CertificateService,
    certificate_result_payload,
    generate_certificate_id,
)
from app.services.rendering_service import CertificateRenderer

from tests.conftest import recipient


@pytest.fixture
def database(settings: Settings) -> Database:
    database = Database(settings.database_url)
    database.create_all()
    yield database
    database.dispose()


@pytest.fixture
def service(database: Database, settings: Settings) -> CertificateService:
    return CertificateService(database, CertificateRenderer(settings))


@pytest.fixture
def job(database: Database) -> GenerationJob:
    with database.session_factory() as session:
        job = GenerationJob(
            job_id="job_test0001",
            event_name="Python Workshop",
            event_date=date(2026, 10, 8),
            total_count=3,
        )
        session.add(job)
        session.commit()
        return job


# -- ID generation ---------------------------------------------------------
@pytest.mark.parametrize(
    "sequence, expected",
    [
        (1, "CERT-2026-000001"),
        (42, "CERT-2026-000042"),
        (999999, "CERT-2026-999999"),
    ],
)
def test_certificate_ids_are_padded_to_six_digits(sequence: int, expected: str) -> None:
    assert generate_certificate_id(sequence, year=2026) == expected


@pytest.mark.parametrize("sequence", [0, -1, 1_000_000])
def test_certificate_sequence_is_range_checked(sequence: int) -> None:
    with pytest.raises(ValueError):
        generate_certificate_id(sequence, year=2026)


# -- receipts --------------------------------------------------------------
def test_receipts_are_numbered_consecutively(service: CertificateService, job: GenerationJob) -> None:
    created = service.create_receipts(
        job.id, [recipient(1), recipient(2), recipient(3)], year=2026
    )

    assert created == 3
    certificates = service.list_certificates(job.id)
    assert [c.certificate_id for c in certificates] == [
        "CERT-2026-000001",
        "CERT-2026-000002",
        "CERT-2026-000003",
    ]
    assert all(c.status is CertificateStatus.PENDING for c in certificates)
    assert all(c.file_path is None for c in certificates)


def test_receipts_keep_the_recipient_details(
    service: CertificateService, job: GenerationJob
) -> None:
    service.create_receipts(
        job.id,
        [recipient(1, name="Aditya Singh", email="aditya@example.com", course="CSE")],
        year=2026,
    )

    certificate = service.list_certificates(job.id)[0]
    assert certificate.recipient_name == "Aditya Singh"
    assert certificate.recipient_email == "aditya@example.com"
    assert certificate.course_name == "CSE"


def test_receipts_continue_after_the_highest_existing_id(
    service: CertificateService, job: GenerationJob
) -> None:
    service.create_receipts(job.id, [recipient(1), recipient(2)], year=2026)

    with service.database.session_factory() as session:
        job_two = GenerationJob(
            job_id="job_test0002",
            event_name="Second Event",
            event_date=date(2026, 10, 9),
            total_count=1,
        )
        session.add(job_two)
        session.commit()
        second_pk = job_two.id

    service.create_receipts(second_pk, [recipient(3)], year=2026)

    assert service.list_certificates(second_pk)[0].certificate_id == "CERT-2026-000003"


def test_a_new_year_restarts_the_sequence(
    service: CertificateService, job: GenerationJob
) -> None:
    service.create_receipts(job.id, [recipient(1)], year=2026)

    with service.database.session_factory() as session:
        job_two = GenerationJob(
            job_id="job_test0003",
            event_name="Next Year",
            event_date=date(2027, 1, 5),
            total_count=1,
        )
        session.add(job_two)
        session.commit()
        second_pk = job_two.id

    service.create_receipts(second_pk, [recipient(2)], year=2027)

    assert service.list_certificates(second_pk)[0].certificate_id == "CERT-2027-000001"


def test_an_unusual_id_in_the_database_does_not_break_allocation(
    service: CertificateService, job: GenerationJob
) -> None:
    """The next sequence comes from the numeric column, not by parsing IDs."""
    with service.database.session_factory() as session:
        session.add(
            Certificate(
                job_id=job.id,
                certificate_id="CERT-2026-ABC123",
                issue_year=2026,
                sequence=7,
                recipient_name="Legacy Row",
                course_name="Legacy",
            )
        )
        session.commit()

    service.create_receipts(job.id, [recipient(1)], year=2026)

    allocated = [
        c.certificate_id for c in service.list_certificates(job.id) if c.sequence == 8
    ]
    assert allocated == ["CERT-2026-000008"]


# -- rendering -------------------------------------------------------------
def test_rendering_marks_the_certificate_successful_and_writes_the_pdf(
    service: CertificateService, job: GenerationJob
) -> None:
    service.create_receipts(job.id, [recipient(1)], year=2026)
    certificate = service.list_certificates(job.id)[0]

    path = service.render_certificate(certificate.id)

    assert path.name == "CERT-2026-000001.pdf"
    assert path.read_bytes().startswith(b"%PDF")

    stored = service.get_certificate("CERT-2026-000001")
    assert stored.status is CertificateStatus.SUCCESS
    assert stored.file_path == str(path)
    assert stored.completed_at is not None
    assert stored.error_message is None


def test_rendering_uses_the_job_event_details(
    service: CertificateService, job: GenerationJob, monkeypatch: pytest.MonkeyPatch
) -> None:
    service.create_receipts(job.id, [recipient(1)], year=2026)
    certificate = service.list_certificates(job.id)[0]

    seen = {}
    original = service.renderer.render_to_storage

    def capture(content):
        seen["content"] = content
        return original(content)

    monkeypatch.setattr(service.renderer, "render_to_storage", capture)
    service.render_certificate(certificate.id)

    assert seen["content"].event_name == "Python Workshop"
    assert seen["content"].event_date == date(2026, 10, 8)
    assert seen["content"].recipient_name == "Recipient 1"


def test_rendering_an_unknown_certificate_raises(service: CertificateService) -> None:
    with pytest.raises(CertificateNotFound):
        service.render_certificate(999999)


def test_mark_failed_records_the_reason(
    service: CertificateService, job: GenerationJob
) -> None:
    service.create_receipts(job.id, [recipient(1)], year=2026)
    certificate = service.list_certificates(job.id)[0]

    assert service.mark_failed(certificate.id, "Template not found") is True

    stored = service.get_certificate("CERT-2026-000001")
    assert stored.status is CertificateStatus.FAILED
    assert stored.error_message == "Template not found"
    assert stored.file_path is None
    assert stored.completed_at is not None


def test_mark_failed_on_a_deleted_row_is_not_an_error(service: CertificateService) -> None:
    assert service.mark_failed(424242, "gone") is False


# -- download --------------------------------------------------------------
def test_download_returns_a_readable_pdf(
    service: CertificateService, job: GenerationJob
) -> None:
    service.create_receipts(job.id, [recipient(1)], year=2026)
    service.render_certificate(service.list_certificates(job.id)[0].id)

    download = service.download("CERT-2026-000001")

    assert download.filename == "CERT-2026-000001.pdf"
    assert download.content_type == "application/pdf"
    assert download.stream.read(4) == b"%PDF"
    download.stream.close()


def test_download_of_an_unknown_certificate_raises(service: CertificateService) -> None:
    with pytest.raises(CertificateNotFound):
        service.download("CERT-2026-000404")


def test_download_before_rendering_is_refused(
    service: CertificateService, job: GenerationJob
) -> None:
    service.create_receipts(job.id, [recipient(1)], year=2026)

    with pytest.raises(CertificateNotFound) as error:
        service.download("CERT-2026-000001")

    assert "PENDING" in str(error.value)


def test_download_of_a_failed_certificate_is_refused(
    service: CertificateService, job: GenerationJob
) -> None:
    service.create_receipts(job.id, [recipient(1)], year=2026)
    certificate = service.list_certificates(job.id)[0]
    service.mark_failed(certificate.id, "boom")

    with pytest.raises(CertificateNotFound) as error:
        service.download("CERT-2026-000001")

    assert "FAILED" in str(error.value)


def test_download_reports_a_missing_file_rather_than_a_path(
    service: CertificateService, job: GenerationJob
) -> None:
    service.create_receipts(job.id, [recipient(1)], year=2026)
    certificate = service.list_certificates(job.id)[0]
    path = service.render_certificate(certificate.id)
    path.unlink()  # e.g. someone cleaned the storage directory

    with pytest.raises(CertificateNotFound) as error:
        service.download("CERT-2026-000001")

    assert "missing" in str(error.value).lower()
    assert str(service.renderer.storage_dir) not in str(error.value)


# -- payload shaping -------------------------------------------------------
def test_payload_hides_the_download_url_until_the_pdf_exists(
    service: CertificateService, job: GenerationJob
) -> None:
    service.create_receipts(job.id, [recipient(1)], year=2026)
    certificate = service.list_certificates(job.id)[0]

    pending = certificate_result_payload(certificate)
    assert pending["status"] is CertificateStatus.PENDING
    assert pending["download_url"] is None
    assert "file_path" not in pending

    service.render_certificate(certificate.id)
    ready = certificate_result_payload(service.get_certificate("CERT-2026-000001"))

    assert ready["download_url"] == "/api/v1/certificates/CERT-2026-000001"
    assert ready["course"] == "Course 1"
    assert ready["error"] is None


def test_payload_of_a_failed_certificate_carries_the_reason(
    service: CertificateService, job: GenerationJob
) -> None:
    service.create_receipts(job.id, [recipient(1)], year=2026)
    certificate = service.list_certificates(job.id)[0]
    service.mark_failed(certificate.id, "Template not found")

    payload = certificate_result_payload(service.get_certificate("CERT-2026-000001"))

    assert payload["status"] is CertificateStatus.FAILED
    assert payload["error"] == "Template not found"
    assert payload["download_url"] is None
