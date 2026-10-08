"""HTTP contract: submission, progress, per-recipient results and downloads."""

from __future__ import annotations

from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.database import Database
from app.main import API_PREFIX, create_app

from tests.conftest import job_payload, recipient, run_job, wait_for_job

JOBS = f"{API_PREFIX}/jobs"


# -- health ----------------------------------------------------------------
def test_health_reports_a_ready_service(client: TestClient) -> None:
    response = client.get(f"{API_PREFIX}/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"]["ready"] is True
    assert payload["certificate_template"]["ready"] is True


def test_health_degrades_when_the_template_is_unusable(project_layout: Dict[str, Any]) -> None:
    broken = Settings(
        database_url=f"sqlite:///{project_layout['database'].as_posix()}",
        certificate_storage_dir=project_layout["storage"],
        certificate_template_path=project_layout["template"].parent / "gone.png",
        font_path=None,
    )
    with TestClient(create_app(settings=broken, enable_legacy_portal=False)) as test_client:
        payload = test_client.get(f"{API_PREFIX}/health").json()

    assert payload["status"] == "degraded"
    assert payload["certificate_template"]["ready"] is False
    assert payload["database"]["ready"] is True


# -- submission ------------------------------------------------------------
def test_submitting_a_job_returns_202_and_a_job_id(client: TestClient) -> None:
    response = client.post(JOBS, json=job_payload())

    assert response.status_code == 202
    payload = response.json()
    assert payload["job_id"].startswith("job_")
    assert payload["status"] == "PENDING"
    assert payload["total"] == 2
    assert payload["completed"] == 0
    assert payload["failed"] == 0


def test_submission_returns_before_generation_finishes(client: TestClient) -> None:
    """The whole point of a bulk endpoint: a big list must not block the request."""
    payload = job_payload([recipient(index) for index in range(1, 26)])

    response = client.post(JOBS, json=payload)

    assert response.status_code == 202
    assert response.json()["total"] == 25
    final = wait_for_job(client, response.json()["job_id"])
    assert final["completed"] == 25


@pytest.mark.parametrize(
    "body, reason",
    [
        ({}, "missing fields"),
        ({"event_name": "E", "date": "2026-10-08"}, "no recipients"),
        (job_payload([]), "empty recipient list"),
        (job_payload([{"name": "", "course": "CSE"}]), "blank name"),
        (job_payload([{"name": "   ", "course": "CSE"}]), "whitespace-only name"),
        (job_payload([{"name": "A", "course": ""}]), "blank course"),
        (job_payload([{"name": "A", "course": "C", "email": "not-an-email"}]), "bad email"),
        (job_payload(event_name="   "), "blank event name"),
        (job_payload(date="08-10-2026"), "non-ISO date"),
        (job_payload(date="not-a-date"), "unparseable date"),
        ({"event_name": "E", "date": "2026-10-08", "recipients": [{"name": "A", "course": "C", "extra": 1}]}, "unknown field"),
    ],
)
def test_invalid_payloads_are_rejected_with_422(
    client: TestClient, body: Dict[str, Any], reason: str
) -> None:
    response = client.post(JOBS, json=body)

    assert response.status_code == 422, f"{reason}: {response.text}"


def test_a_job_exceeding_the_recipient_cap_is_rejected(client: TestClient) -> None:
    payload = job_payload([recipient(index) for index in range(1, 1002)])

    response = client.post(JOBS, json=payload)

    assert response.status_code == 422


def test_a_rejected_payload_creates_no_job(client: TestClient) -> None:
    assert client.post(JOBS, json=job_payload([])).status_code == 422

    database = client.app.state.database
    with database.session_factory() as session:
        from app.db.models import GenerationJob

        assert session.query(GenerationJob).count() == 0


def test_recipient_whitespace_is_collapsed(client: TestClient) -> None:
    payload = job_payload([{"name": "  Aditya   Singh ", "course": "  Computer   Science "}])

    job_id = client.post(JOBS, json=payload).json()["job_id"]
    wait_for_job(client, job_id)

    certificate = client.get(f"{JOBS}/{job_id}/certificates").json()[0]
    assert certificate["recipient_name"] == "Aditya Singh"
    assert certificate["course"] == "Computer Science"


def test_a_blank_email_is_accepted_as_absent(client: TestClient) -> None:
    payload = job_payload([{"name": "Meera Raman", "course": "IT", "email": "   "}])

    job_id = client.post(JOBS, json=payload).json()["job_id"]
    wait_for_job(client, job_id)

    certificate = client.get(f"{JOBS}/{job_id}/certificates").json()[0]
    assert certificate["status"] == "SUCCESS"


# -- progress --------------------------------------------------------------
def test_a_successful_job_reaches_completed(client: TestClient) -> None:
    final = run_job(client, job_payload())

    assert final["status"] == "COMPLETED"
    assert final["completed"] == 2
    assert final["failed"] == 0
    assert final["pending"] == 0
    assert final["progress_percentage"] == 100.0
    assert final["completed_at"] is not None


def test_status_reports_the_event_details(client: TestClient) -> None:
    final = run_job(client, job_payload(event_name="Python Workshop", date="2026-10-08"))

    assert final["event_name"] == "Python Workshop"
    assert final["event_date"] == "2026-10-08"
    assert final["created_at"] is not None


def test_an_unknown_job_is_a_404(client: TestClient) -> None:
    response = client.get(f"{JOBS}/job_deadbeef")

    assert response.status_code == 404
    assert "job_deadbeef" in response.json()["detail"]


def test_certificates_of_an_unknown_job_are_a_404(client: TestClient) -> None:
    assert client.get(f"{JOBS}/job_deadbeef/certificates").status_code == 404


# -- per-recipient results -------------------------------------------------
def test_each_recipient_gets_a_downloadable_certificate(client: TestClient) -> None:
    payload = job_payload([recipient(1), recipient(2), recipient(3)])
    job_id = client.post(JOBS, json=payload).json()["job_id"]
    final = wait_for_job(client, job_id)

    certificates = client.get(f"{JOBS}/{job_id}/certificates").json()

    assert final["completed"] == 3
    assert len(certificates) == 3
    assert [c["recipient_name"] for c in certificates] == [
        "Recipient 1",
        "Recipient 2",
        "Recipient 3",
    ]
    assert [c["certificate_id"] for c in certificates] == [
        "CERT-2026-000001",
        "CERT-2026-000002",
        "CERT-2026-000003",
    ]
    for certificate in certificates:
        assert certificate["status"] == "SUCCESS"
        assert certificate["error"] is None
        assert certificate["download_url"] == (
            f"{API_PREFIX}/certificates/{certificate['certificate_id']}"
        )
        assert "file_path" not in certificate


def test_certificates_can_be_filtered_by_status(client: TestClient) -> None:
    job_id = client.post(JOBS, json=job_payload()).json()["job_id"]
    wait_for_job(client, job_id)

    success = client.get(f"{JOBS}/{job_id}/certificates", params={"status": "SUCCESS"}).json()
    failed = client.get(f"{JOBS}/{job_id}/certificates", params={"status": "FAILED"}).json()

    assert len(success) == 2
    assert failed == []


def test_an_invalid_status_filter_is_rejected(client: TestClient) -> None:
    job_id = client.post(JOBS, json=job_payload()).json()["job_id"]
    wait_for_job(client, job_id)

    response = client.get(f"{JOBS}/{job_id}/certificates", params={"status": "NOPE"})

    assert response.status_code == 422


def test_ids_keep_increasing_across_jobs(client: TestClient) -> None:
    first = wait_for_job(client, client.post(JOBS, json=job_payload()).json()["job_id"])
    second = wait_for_job(client, client.post(JOBS, json=job_payload()).json()["job_id"])

    first_ids = [c["certificate_id"] for c in client.get(f"{JOBS}/{first['job_id']}/certificates").json()]
    second_ids = [c["certificate_id"] for c in client.get(f"{JOBS}/{second['job_id']}/certificates").json()]

    assert first_ids == ["CERT-2026-000001", "CERT-2026-000002"]
    assert second_ids == ["CERT-2026-000003", "CERT-2026-000004"]


# -- downloads -------------------------------------------------------------
def test_a_certificate_downloads_as_a_pdf(client: TestClient) -> None:
    job_id = client.post(JOBS, json=job_payload([recipient(1)])).json()["job_id"]
    wait_for_job(client, job_id)
    url = client.get(f"{JOBS}/{job_id}/certificates").json()[0]["download_url"]

    response = client.get(url)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert 'attachment; filename="CERT-2026-000001.pdf"' == response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")


@pytest.mark.parametrize(
    "certificate_id",
    [
        "CERT-2026-000404",  # never issued
        "not-a-certificate-id",
        "CERT-2026-000001.pdf",
        "Aditya_Singh",  # the legacy name-based scheme
        "..%2F..%2Fetc%2Fpasswd",
    ],
)
def test_unknown_or_malformed_certificate_ids_are_404(
    client: TestClient, certificate_id: str
) -> None:
    response = client.get(f"{API_PREFIX}/certificates/{certificate_id}")

    assert response.status_code == 404


def test_a_certificate_that_failed_cannot_be_downloaded(client: TestClient) -> None:
    """The listing explains why; the download route only has one answer."""
    job_id = client.post(JOBS, json=job_payload([recipient(1)])).json()["job_id"]
    wait_for_job(client, job_id)
    certificate_id = client.get(f"{JOBS}/{job_id}/certificates").json()[0]["certificate_id"]

    # Simulate the PDF going missing (someone cleaned the storage directory).
    (client.app.state.renderer.storage_dir / f"{certificate_id}.pdf").unlink()

    response = client.get(f"{API_PREFIX}/certificates/{certificate_id}")

    assert response.status_code == 404
    assert str(client.app.state.renderer.storage_dir) not in response.json()["detail"]


# -- failure paths ---------------------------------------------------------
def test_a_broken_template_fails_each_certificate_but_not_the_job(
    project_layout: Dict[str, Any],
) -> None:
    """One bad run must be visible per recipient, never a 500 for the whole batch."""
    settings = Settings(
        database_url=f"sqlite:///{project_layout['database'].as_posix()}",
        certificate_storage_dir=project_layout["storage"],
        certificate_template_path=project_layout["template"].parent / "missing.png",
        font_path=None,
    )
    with TestClient(create_app(settings=settings, enable_legacy_portal=False)) as client:
        job_id = client.post(JOBS, json=job_payload([recipient(1), recipient(2)])).json()["job_id"]
        final = wait_for_job(client, job_id)
        certificates = client.get(f"{JOBS}/{job_id}/certificates").json()

    assert final["status"] == "FAILED"
    assert final["failed"] == 2
    assert final["completed"] == 0
    assert all(c["status"] == "FAILED" for c in certificates)
    assert all("missing.png" in c["error"] for c in certificates)
    assert all(c["download_url"] is None for c in certificates)


# -- landing page ----------------------------------------------------------
def test_the_landing_page_serves_the_api_console(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Bulk Certificate Generator" in response.text


def test_the_openapi_schema_lists_the_bulk_endpoints(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert set(paths) >= {
        f"{API_PREFIX}/jobs",
        f"{API_PREFIX}/jobs/{{job_id}}",
        f"{API_PREFIX}/jobs/{{job_id}}/certificates",
        f"{API_PREFIX}/certificates/{{certificate_id}}",
        f"{API_PREFIX}/health",
    }


# -- legacy portal ---------------------------------------------------------
def test_the_csv_portal_is_absent_when_no_csv_is_configured(client: TestClient) -> None:
    """The bulk API must work on a machine that has never seen students.csv."""
    assert client.app.state.legacy_enabled is False
    assert client.get("/verify", params={"name": "A", "student_id": "1"}).status_code == 404


def test_the_csv_portal_is_restored_when_a_csv_is_present(
    project_layout: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    csv_path = project_layout["root"] / "students.csv"
    csv_path.write_text(
        "Timestamp,Name,Email_id,Student_Id,Course,Code\n"
        "1/20/2024 15:30:00,Aditya singh,aditya@example.com,25101280272,Workshop-I,ABC123\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CSV_PATH", str(csv_path))
    monkeypatch.setenv("CSV_MANAGEMENT_PATH", str(project_layout["root"] / "management.csv"))
    monkeypatch.setenv("CERTIFICATES_DIR", str(project_layout["root"] / "legacy-certs"))

    settings = Settings(
        database_url=f"sqlite:///{project_layout['database'].as_posix()}",
        certificate_storage_dir=project_layout["storage"],
        certificate_template_path=project_layout["template"],
        font_path=None,
    )

    with TestClient(create_app(settings=settings)) as client:
        assert client.app.state.legacy_enabled is True
        verified = client.get(
            "/verify", params={"name": "aditya singh", "student_id": "25101280272"}
        )

    assert verified.status_code == 200
    assert verified.json()["valid"] is True
    assert verified.json()["course"] == "Workshop-I"
