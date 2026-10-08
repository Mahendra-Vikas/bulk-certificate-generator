"""Certificate IDs double as file names, so these guards matter."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.utils.file_utils import (
    certificate_pdf_path,
    delete_file,
    download_url,
    ensure_directory,
    is_valid_certificate_id,
)


@pytest.mark.parametrize(
    "certificate_id",
    ["CERT-2026-000001", "CERT-1999-999999", "CERT-2026-100000"],
)
def test_valid_certificate_ids_are_accepted(certificate_id: str) -> None:
    assert is_valid_certificate_id(certificate_id) is True


@pytest.mark.parametrize(
    "certificate_id",
    [
        "",
        "CERT-2026-1",  # sequence is not padded to six digits
        "CERT-26-000001",  # year is not four digits
        "CERT-2026-0000001",  # one digit too many
        "CERT-2026-00A001",
        "Aditya_Singh",  # the legacy name-based scheme
        "../CERT-2026-000001",
        "CERT-2026-000001/../secret",
        "CERT-2026-000001.pdf",
        "cert-2026-000001",  # IDs are upper case
    ],
)
def test_malformed_certificate_ids_are_rejected(certificate_id: str) -> None:
    assert is_valid_certificate_id(certificate_id) is False


def test_pdf_path_uses_the_storage_directory(tmp_path: Path) -> None:
    assert (
        certificate_pdf_path(tmp_path, "CERT-2026-000042")
        == tmp_path / "CERT-2026-000042.pdf"
    )


@pytest.mark.parametrize(
    "certificate_id",
    ["../../etc/passwd", "Aditya_Singh", "", "CERT-2026-000001/../x"],
)
def test_pdf_path_refuses_to_escape_the_storage_directory(
    tmp_path: Path, certificate_id: str
) -> None:
    with pytest.raises(ValueError):
        certificate_pdf_path(tmp_path, certificate_id)


def test_download_url_points_at_the_certificate_route() -> None:
    assert download_url("CERT-2026-000007") == "/api/v1/certificates/CERT-2026-000007"


def test_ensure_directory_is_idempotent(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "c"
    assert ensure_directory(nested) == nested
    assert ensure_directory(nested).is_dir()


def test_delete_file_ignores_missing_files(tmp_path: Path) -> None:
    delete_file(tmp_path / "never-existed.pdf")  # must not raise

    existing = tmp_path / "exists.pdf"
    existing.write_bytes(b"%PDF-1.7")
    delete_file(existing)
    assert not existing.exists()
