"""Filesystem helpers shared by the API and the service layer."""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

#: Certificate IDs double as file names, so the format is strictly enforced.
CERTIFICATE_ID_PATTERN = re.compile(r"CERT-\d{4}-\d{6}")

#: Public download route for one certificate.
DOWNLOAD_URL_TEMPLATE = "/api/v1/certificates/{certificate_id}"


def ensure_directory(path: Path) -> Path:
    """Create ``path`` (and parents) if needed and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_valid_certificate_id(certificate_id: str) -> bool:
    """True when the value matches the generated ``CERT-YYYY-NNNNNN`` format."""
    return bool(CERTIFICATE_ID_PATTERN.fullmatch(certificate_id or ""))


def certificate_pdf_path(storage_dir: Path, certificate_id: str) -> Path:
    """Absolute PDF path for a certificate ID.

    The ID is validated before it is used as a filename, so a caller can never
    escape ``storage_dir`` with a value such as ``../../etc/passwd``.
    """
    if not is_valid_certificate_id(certificate_id):
        raise ValueError(f"Invalid certificate id: {certificate_id!r}")
    return storage_dir / f"{certificate_id}.pdf"


def download_url(certificate_id: str) -> str:
    """Relative URL the client can call to download a generated certificate."""
    return DOWNLOAD_URL_TEMPLATE.format(certificate_id=certificate_id)


def delete_file(path: Path) -> None:
    """Best-effort removal; a missing file is not an error."""
    try:
        path.unlink(missing_ok=True)
    except OSError:  # pragma: no cover - defensive, e.g. file locked on Windows
        logger.warning("Could not delete %s", path, exc_info=True)
