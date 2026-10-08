"""Application configuration.

Every setting has a working local default, so the project runs with no
environment variables set at all. Each one can be overridden through the
environment (optionally via a ``.env`` file) - see ``.env.example``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:  # python-dotenv is optional; the application works without a .env file.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - only when python-dotenv is absent
    pass


#: Repository root (the folder that contains ``app/``, ``templates/`` and ``tests/``).
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_TEMPLATE_PATH = PROJECT_ROOT / "templates" / "Certificate_template.png"
DEFAULT_STORAGE_DIR = PROJECT_ROOT / "storage" / "certificates"
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "certificate_generator.db"


def _resolve_path(value: str, default: Path) -> Path:
    """Resolve an environment path relative to the project root."""
    raw = (value or "").strip()
    if not raw:
        return default
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate


@dataclass(frozen=True)
class Settings:
    """Runtime settings, resolved once when the application is created."""

    database_url: str
    certificate_storage_dir: Path
    certificate_template_path: Path
    font_path: Path | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        """Build settings from environment variables, falling back to defaults."""
        database_url = (os.getenv("DATABASE_URL") or "").strip()
        if not database_url:
            database_url = f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"

        font_value = (os.getenv("CERTIFICATE_FONT_PATH") or "").strip()

        return cls(
            database_url=database_url,
            certificate_storage_dir=_resolve_path(
                os.getenv("CERTIFICATE_STORAGE_DIR", ""), DEFAULT_STORAGE_DIR
            ),
            certificate_template_path=_resolve_path(
                os.getenv("CERTIFICATE_TEMPLATE_PATH", ""), DEFAULT_TEMPLATE_PATH
            ),
            font_path=_resolve_path(font_value, DEFAULT_TEMPLATE_PATH.parent)
            if font_value
            else None,
        )
