"""Bulk Certificate Generator - application entry point.

``create_app()`` is the single place where the pieces are wired together: the
database engine, the Pillow renderer, the certificate/job services and the
routers. Tests call the same factory and simply pass different
:class:`~app.core.config.Settings`, which is why nothing here depends on
module-level globals.

Routes:

* ``/api/v1/...``  - bulk generation jobs and certificate downloads
* ``/``, ``/verify``, ``/certificate``, ``/generate-all`` - the original
  CSV-driven portal, served by ``templates/index.html``. It stays available as
  long as a students CSV is present, so existing users of the portal are not
  cut off by the bulk API.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, List, Optional

try:  # python-dotenv is optional; environment variables win when it is absent.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - only without python-dotenv installed
    pass

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import certificates as certificate_routes
from app.api.routes import health as health_routes
from app.api.routes import jobs as job_routes
from app.core.config import PROJECT_ROOT, Settings
from app.csv_handler import CSVHandler
from app.db.database import Database
from app.services.certificate_service import CertificateService
from app.services.job_service import JobService
from app.services.rendering_service import CertificateRenderer
from app.utils.file_utils import ensure_directory

logger = logging.getLogger(__name__)

#: Prefix for every JSON endpoint.
API_PREFIX = "/api/v1"

TEMPLATES_DIR = PROJECT_ROOT / "templates"
PORTAL_HTML = TEMPLATES_DIR / "index.html"
API_HTML = TEMPLATES_DIR / "api.html"

#: Legacy CSV defaults, kept so the original endpoints behave as before.
DEFAULT_STUDENTS_CSV = "students.csv"
DEFAULT_MANAGEMENT_CSV = "management.csv"
DEFAULT_LEGACY_OUTPUT_DIR = "certificates"

#: Default import path of the legacy template, which keeps its own file name.
LEGACY_TEMPLATE_IMAGE = "templates/Certificate_template.png"


def _as_abs(path_str: str) -> str:
    """Resolve a possibly Windows-style path against the project root."""
    normalized = (path_str or "").replace("\\", "/")
    candidate = Path(normalized)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return str(candidate)


def _allowed_origins() -> List[str]:
    """CORS origins from ``CORS_ALLOW_ORIGINS`` (comma separated)."""
    import os

    raw = os.getenv("CORS_ALLOW_ORIGINS", "*")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return origins or ["*"]


def _admin_key_accepted(provided: str, expected: str) -> bool:
    """True when the bulk endpoints may run.

    An unset ``ADMIN_KEY`` leaves the check disabled, matching the original
    behaviour: the guard exists for deployments that configure a key.
    """
    return not expected or provided == expected


# -- legacy CSV portal -----------------------------------------------------
def _build_legacy_router(
    csv_handler: Optional[CSVHandler],
    cert_generator,
    admin_key: str,
):
    """The original student/management endpoints, unchanged in behaviour.

    Returns ``None`` when no students CSV can be found, in which case the bulk
    API is the only surface the application exposes.
    """
    from fastapi import APIRouter

    router = APIRouter(tags=["legacy"])
    expected_admin_key = admin_key

    @router.get("/verify", summary="Verify a student against the CSV records")
    async def verify_certificate(name: str, student_id: str):
        try:
            student = csv_handler.find_student_by_name_and_id(name, student_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=f"Student database CSV not available: {exc}")
        except Exception as exc:  # noqa: BLE001 - surfaced as a 500, never a crash
            raise HTTPException(status_code=500, detail=f"Unexpected error while verifying student: {exc}")

        if not student:
            raise HTTPException(
                status_code=404,
                detail=f"Student not found with name: {name} and ID: {student_id}",
            )

        return {
            "name": student.get("Name"),
            "email": student.get("Email_id"),
            "student_id": student.get("Student_Id"),
            "course": student.get("Course"),
            "certificate_id": csv_handler.generate_certificate_id(
                student.get("Student_Id"), student.get("Name")
            ),
            "valid": True,
        }

    @router.get("/certificate", summary="Download a student certificate (legacy)")
    async def get_certificate(
        name: str,
        student_id: str,
        force: bool = Query(False, description="Regenerate even if the PDF already exists"),
    ):
        try:
            student = csv_handler.find_student_by_name_and_id(name, student_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=f"Student database CSV not available: {exc}")

        if not student:
            raise HTTPException(
                status_code=404,
                detail=f"Student not found with name: {name} and ID: {student_id}",
            )

        certificate_id = csv_handler.generate_certificate_id(
            student.get("Student_Id"), student.get("Name")
        )
        if force or not cert_generator.certificate_exists(certificate_id):
            try:
                cert_generator.generate_certificate(
                    student_name=student.get("Name"),
                    certificate_id=certificate_id,
                    course=None,
                )
            except Exception as exc:  # noqa: BLE001 - reported to the caller
                raise HTTPException(status_code=500, detail=f"Error generating certificate: {exc}")

        return FileResponse(
            path=cert_generator.get_certificate_path(certificate_id),
            media_type="application/pdf",
            filename=f"{certificate_id}.pdf",
        )

    @router.get("/generate-all", summary="Bulk-generate student certificates (legacy)")
    async def generate_all_certificates(admin_key: str = Query(...)):
        if not _admin_key_accepted(admin_key, expected_admin_key):
            raise HTTPException(status_code=403, detail="Invalid admin key")

        try:
            students = csv_handler.get_all_students()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=f"Student database CSV not available: {exc}")

        generated, skipped = [], []
        for student in students:
            student_id = student.get("Student_Id")
            name = student.get("Name")
            certificate_id = csv_handler.generate_certificate_id(student_id, name)

            if cert_generator.certificate_exists(certificate_id):
                skipped.append(certificate_id)
                continue

            cert_generator.generate_certificate(
                student_name=name, certificate_id=certificate_id, course=student.get("Course")
            )
            generated.append(certificate_id)

        return {
            "success": True,
            "total_students": len(students),
            "generated": len(generated),
            "skipped": len(skipped),
            "generated_ids": generated,
            "skipped_ids": skipped,
        }

    @router.get("/verify-management", summary="Verify a management member (legacy)")
    async def verify_management_certificate(name: str, mgmt_id: str):
        try:
            person = csv_handler.find_management_by_name_and_id(name, mgmt_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=f"Management database CSV not available: {exc}")

        if not person:
            raise HTTPException(
                status_code=404,
                detail=f"Management member not found with name: {name} and ID: {mgmt_id}",
            )

        return {
            "name": person.get("Name"),
            "email": person.get("Email_id"),
            "position": person.get("Position"),
            "certificate_id": csv_handler.generate_management_certificate_id(
                person.get("Student_Id"), person.get("Name")
            ),
            "valid": True,
        }

    @router.get("/certificate-management", summary="Download a management certificate (legacy)")
    async def get_management_certificate(
        name: str,
        mgmt_id: str,
        force: bool = Query(False, description="Regenerate even if the PDF already exists"),
    ):
        try:
            person = csv_handler.find_management_by_name_and_id(name, mgmt_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=f"Management database CSV not available: {exc}")

        if not person:
            raise HTTPException(
                status_code=404,
                detail=f"Management member not found with name: {name} and ID: {mgmt_id}",
            )

        certificate_id = csv_handler.generate_management_certificate_id(
            person.get("Student_Id"), person.get("Name")
        )
        if force or not cert_generator.certificate_exists(certificate_id):
            try:
                cert_generator.generate_management_certificate(
                    person_name=person.get("Name"), certificate_id=certificate_id
                )
            except Exception as exc:  # noqa: BLE001 - reported to the caller
                raise HTTPException(
                    status_code=500, detail=f"Error generating management certificate: {exc}"
                )

        return FileResponse(
            path=cert_generator.get_certificate_path(certificate_id),
            media_type="application/pdf",
            filename=f"{certificate_id}.pdf",
        )

    @router.get("/generate-all-management", summary="Bulk-generate management certificates (legacy)")
    async def generate_all_management_certificates(admin_key: str = Query(...)):
        if not _admin_key_accepted(admin_key, expected_admin_key):
            raise HTTPException(status_code=403, detail="Invalid admin key")

        try:
            management = csv_handler.get_all_management()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=f"Management database CSV not available: {exc}")

        generated, skipped = [], []
        for person in management:
            certificate_id = csv_handler.generate_management_certificate_id(
                person.get("Student_Id"), person.get("Name")
            )
            if cert_generator.certificate_exists(certificate_id):
                skipped.append(certificate_id)
                continue

            cert_generator.generate_management_certificate(
                person_name=person.get("Name"), certificate_id=certificate_id
            )
            generated.append(certificate_id)

        return {
            "success": True,
            "total_management": len(management),
            "generated": len(generated),
            "skipped": len(skipped),
            "generated_ids": generated,
            "skipped_ids": skipped,
        }

    return router


def create_app(
    settings: Optional[Settings] = None,
    enable_legacy_portal: Optional[bool] = None,
) -> FastAPI:
    """Build the FastAPI application.

    Args:
        settings: Override the environment-derived settings (used by tests).
        enable_legacy_portal: Force the CSV portal on or off; by default it is
            enabled exactly when a students CSV can be found.
    """
    import os

    resolved = settings or Settings.from_env()
    admin_key = os.getenv("ADMIN_KEY", "")

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.database.create_all()
        ensure_directory(application.state.renderer.storage_dir)
        logger.info("Certificate generator ready: %s", application.state.renderer.describe())
        if application.state.legacy_enabled:
            logger.info("Legacy CSV portal enabled")
        try:
            yield
        finally:
            application.state.database.dispose()

    application = FastAPI(
        title="Bulk Certificate Generator",
        description=(
            "Submit a list of recipients and download personalised PDF "
            "certificates. Generation runs in the background; poll the job for "
            "progress."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- services (one set per application, reachable through app.state) ----
    database = Database(resolved.database_url)
    renderer = CertificateRenderer(resolved)
    certificate_service = CertificateService(database, renderer)
    job_service = JobService(database, certificate_service)

    application.state.settings = resolved
    application.state.database = database
    application.state.renderer = renderer
    application.state.certificate_service = certificate_service
    application.state.job_service = job_service

    # -- legacy CSV portal --------------------------------------------------
    csv_handler = CSVHandler(
        _as_abs(os.getenv("CSV_PATH", DEFAULT_STUDENTS_CSV)),
        management_csv_path=_as_abs(os.getenv("CSV_MANAGEMENT_PATH", DEFAULT_MANAGEMENT_CSV)),
    )
    legacy_enabled = (
        enable_legacy_portal
        if enable_legacy_portal is not None
        else csv_handler.validate_csv_structure()
    )
    application.state.legacy_enabled = legacy_enabled
    application.state.csv_handler = csv_handler

    if legacy_enabled:
        from app.certificate_generator import CertificateGenerator

        cert_generator = CertificateGenerator(
            template_path=_as_abs(os.getenv("CERTIFICATE_TEMPLATE_IMAGE", LEGACY_TEMPLATE_IMAGE)),
            output_dir=_as_abs(os.getenv("CERTIFICATES_DIR", DEFAULT_LEGACY_OUTPUT_DIR)),
            management_template_path=_as_abs(
                os.getenv("CERTIFICATE_MANAGEMENT_TEMPLATE_IMAGE", "templates/CertificateManagement.jpeg")
            ),
        )
        application.state.cert_generator = cert_generator
        application.include_router(
            _build_legacy_router(csv_handler, cert_generator, admin_key)
        )

    # -- new API ------------------------------------------------------------
    application.include_router(health_routes.router, prefix=API_PREFIX)
    application.include_router(job_routes.router, prefix=API_PREFIX)
    application.include_router(certificate_routes.router, prefix=API_PREFIX)

    if TEMPLATES_DIR.exists():
        application.mount("/static", StaticFiles(directory=str(TEMPLATES_DIR)), name="static")

    # -- landing page -------------------------------------------------------
    @application.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def home(request: Request) -> HTMLResponse:
        """The bulk API console, or the CSV portal when one is configured."""
        page = PORTAL_HTML if request.app.state.legacy_enabled else API_HTML
        if not page.exists():
            raise HTTPException(status_code=500, detail="Landing page template not found")
        return HTMLResponse(content=page.read_text(encoding="utf-8"))

    return application


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
