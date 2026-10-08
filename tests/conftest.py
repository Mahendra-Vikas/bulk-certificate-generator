"""Shared fixtures.

Every test gets its own SQLite file, storage directory and template image, so
tests never touch the developer's real database, certificates or template.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.core.config import Settings
from app.main import create_app

API = "/api/v1"

#: How long a test waits for a background job before giving up.
JOB_TIMEOUT_SECONDS = 30.0


def _write_template(path: Path, size: tuple[int, int] = (800, 600)) -> Path:
    """Create a stand-in certificate template.

    Deliberately tiny compared to the real 2400x1792 template: the rendering
    code works in ratios, so a small image exercises the same code path in a
    fraction of the time.
    """
    image = Image.new("RGB", size, (252, 250, 245))
    draw = ImageDraw.Draw(image)
    draw.rectangle([20, 20, size[0] - 20, size[1] - 20], outline=(180, 175, 160), width=3)
    draw.line([(100, 300), (size[0] - 100, 300)], fill=(120, 115, 105), width=2)
    image.save(path, "PNG")
    return path


@pytest.fixture
def project_layout(tmp_path: Path) -> Dict[str, Path]:
    """Temporary database, storage directory and template for one test."""
    storage = tmp_path / "storage" / "certificates"
    storage.mkdir(parents=True, exist_ok=True)
    template = _write_template(tmp_path / "template.png")
    return {
        "root": tmp_path,
        "template": template,
        "storage": storage,
        "database": tmp_path / "test.db",
    }


@pytest.fixture
def settings(project_layout: Dict[str, Path]) -> Settings:
    """Settings pointing every path at the temporary layout."""
    return Settings(
        database_url=f"sqlite:///{project_layout['database'].as_posix()}",
        certificate_storage_dir=project_layout["storage"],
        certificate_template_path=project_layout["template"],
        font_path=None,
    )


@pytest.fixture
def app(settings: Settings):
    """The application under test, with the CSV portal switched off."""
    return create_app(settings=settings, enable_legacy_portal=False)


@pytest.fixture
def client(app):
    """A test client that runs the application's lifespan (creates tables)."""
    with TestClient(app) as test_client:
        yield test_client


def recipient(index: int, **overrides: Any) -> Dict[str, Any]:
    """A valid recipient payload."""
    payload: Dict[str, Any] = {
        "name": f"Recipient {index}",
        "email": f"recipient{index}@example.com",
        "course": f"Course {index}",
    }
    payload.update(overrides)
    return payload


def job_payload(
    recipients: List[Dict[str, Any]] | None = None,
    *,
    event_name: str = "Python Workshop",
    date: str = "2026-10-08",
) -> Dict[str, Any]:
    """A valid ``POST /api/v1/jobs`` body."""
    return {
        "event_name": event_name,
        "date": date,
        "recipients": recipients if recipients is not None else [recipient(1), recipient(2)],
    }


def wait_for_job(
    client: TestClient,
    job_id: str,
    timeout: float = JOB_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Poll a job until it reaches a terminal status, then return the payload."""
    terminal = {"COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"}
    deadline = time.monotonic() + timeout
    payload: Dict[str, Any] = {}

    while time.monotonic() < deadline:
        response = client.get(f"{API}/jobs/{job_id}")
        assert response.status_code == 200, response.text
        payload = response.json()
        if payload["status"] in terminal:
            return payload
        time.sleep(0.05)

    raise AssertionError(f"Job {job_id} did not finish within {timeout}s: {payload}")


def run_job(client: TestClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Submit a job and wait for it to finish, returning the final status."""
    response = client.post(f"{API}/jobs", json=payload)
    assert response.status_code == 202, response.text
    return wait_for_job(client, response.json()["job_id"])
