"""Readiness endpoint.

Answers the one question a deployment platform (or a human) actually asks:
*can this process serve a certificate right now?* - which means the template
must be a readable image and the database must answer a query.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Request
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get("/health", summary="Service readiness")
def health(request: Request) -> Dict[str, Any]:
    """Report database connectivity and template usability."""
    renderer = request.app.state.renderer
    database = request.app.state.database

    template_ready = renderer.is_ready()

    database_error = None
    try:
        with database.session_factory() as session:
            session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - reported, never raised to the client
        database_error = f"{type(exc).__name__}"

    database_ready = database_error is None
    healthy = template_ready and database_ready

    return {
        "status": "ok" if healthy else "degraded",
        "database": {
            "ready": database_ready,
            "error": database_error,
        },
        "certificate_template": {
            "ready": template_ready,
            "name": renderer.template_path.name,
        },
        "renderer": renderer.describe(),
    }
