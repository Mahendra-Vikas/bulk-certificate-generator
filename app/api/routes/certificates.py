"""Certificate download endpoint.

Certificates are addressed by their public ID (``CERT-YYYY-NNNNNN``), so a
client only ever needs the value it received from the job listing.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_certificate_service
from app.services.certificate_service import CertificateNotFound, CertificateService
from app.utils.file_utils import is_valid_certificate_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/certificates", tags=["certificates"])

CertificateServiceDep = Annotated[CertificateService, Depends(get_certificate_service)]


@router.get(
    "/{certificate_id}",
    response_class=StreamingResponse,
    summary="Download a generated certificate",
    responses={
        200: {"content": {"application/pdf": {}}, "description": "The certificate PDF"},
        404: {"description": "Unknown certificate, or it is not ready for download"},
    },
)
def download_certificate(
    certificate_id: Annotated[str, Path(description="e.g. CERT-2026-000042")],
    certificates: CertificateServiceDep,
) -> StreamingResponse:
    """Stream the certificate PDF as a file download.

    A certificate that is still generating, failed, or whose file has been
    removed answers ``404`` as well - the client's next move is the same in
    every case: read the job's certificate listing.
    """
    if not is_valid_certificate_id(certificate_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown certificate: {certificate_id}",
        )

    try:
        download = certificates.download(certificate_id)
    except CertificateNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return StreamingResponse(
        download.stream,
        media_type=download.content_type,
        headers={"Content-Disposition": f'attachment; filename="{download.filename}"'},
    )
