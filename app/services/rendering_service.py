"""Certificate rendering service (the only module that touches Pillow).

The rendering logic is deliberately isolated from the API layer: routes deal
with HTTP and the database, while everything that draws pixels lives here.

Layout is expressed as *ratios* of the template size, not absolute pixels, so
replacing ``templates/Certificate_template.png`` with a different resolution
does not require touching the drawing code. All coordinates and font sizes for
the whole certificate are defined in :data:`DEFAULT_LAYOUT`.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

from app.core.config import Settings
from app.utils.file_utils import certificate_pdf_path, ensure_directory

logger = logging.getLogger(__name__)

#: RGB colour tuples used when drawing text on the template.
NAVY = (27, 42, 91)
NAVY_SOFT = (58, 74, 122)
MUTED = (85, 95, 122)

#: Rendered at 300 DPI, which is the print resolution expected of a certificate.
PDF_RESOLUTION = 300.0

#: Unicode bullet used to separate the metadata fields in the footer line.
SEPARATOR = " • "


class CertificateRenderingError(RuntimeError):
    """Raised when a certificate cannot be drawn.

    The message is safe to show to API clients: it never contains a stack trace
    or an absolute filesystem path.
    """


@dataclass(frozen=True)
class TextFieldLayout:
    """Placement rules for one line of text, expressed as ratios of the template.

    Args:
        center_x_ratio: Horizontal centre as a fraction of the image width.
        center_y_ratio: Vertical centre as a fraction of the image height.
        font_size_ratio: Starting font size as a fraction of the image height.
        max_width_ratio: Maximum line width as a fraction of the image width.
        min_font_size: Smallest font size the auto-fit is allowed to shrink to.
        color: RGB fill colour.
    """

    center_x_ratio: float
    center_y_ratio: float
    font_size_ratio: float
    max_width_ratio: float
    min_font_size: int
    color: Tuple[int, int, int]


@dataclass(frozen=True)
class CertificateLayout:
    """Every text field drawn onto the template."""

    name: TextFieldLayout
    course: TextFieldLayout
    footer: TextFieldLayout


#: Measured from ``templates/Certificate_template.png`` (2400 x 1792).
#:
#: The template already pre-prints the "CERTIFICATE OF PARTICIPATION" header, the
#: event paragraph with its own date, the signature block and the college logo.
#: The only blank line is the ruled line under "THIS CERTIFICATE IS AWARDED TO.",
#: so the recipient name is centred on it, the course is a subtitle just above
#: it, and the event/date/certificate-id metadata goes in the free band below the
#: signature block.
DEFAULT_LAYOUT = CertificateLayout(
    name=TextFieldLayout(
        center_x_ratio=0.365,
        center_y_ratio=0.475,
        font_size_ratio=0.055,
        max_width_ratio=0.56,
        min_font_size=18,
        color=NAVY,
    ),
    course=TextFieldLayout(
        center_x_ratio=0.365,
        center_y_ratio=0.522,
        font_size_ratio=0.021,
        max_width_ratio=0.52,
        min_font_size=14,
        color=NAVY_SOFT,
    ),
    footer=TextFieldLayout(
        center_x_ratio=0.365,
        center_y_ratio=0.955,
        font_size_ratio=0.017,
        max_width_ratio=0.60,
        min_font_size=12,
        color=MUTED,
    ),
)


@dataclass(frozen=True)
class CertificateContent:
    """The values rendered onto one certificate."""

    recipient_name: str
    course_name: str
    event_name: str
    event_date: date
    certificate_id: str

    def footer_text(self) -> str:
        """Single metadata line placed beneath the signature block."""
        return SEPARATOR.join(
            (self.event_name, self.event_date.strftime("%d %B %Y"), self.certificate_id)
        )


def _windows_font_directories() -> Sequence[Path]:
    """Windows font directories, derived from the environment (never hardcoded)."""
    candidates = []
    for variable in ("WINDIR", "SystemRoot"):
        root = os.environ.get(variable)
        if root:
            candidates.append(Path(root) / "Fonts")
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Microsoft" / "Windows" / "Fonts")
    return candidates


def _candidate_font_paths(explicit: Optional[Path]) -> Sequence[Path]:
    """Font files to try, in preference order.

    A serif face is preferred first because the template's own typography is
    serif; the remaining entries are portability fallbacks.
    """
    preferred_names = (
        "georgiab.ttf",
        "georgia.ttf",
        "timesbd.ttf",
        "times.ttf",
        "constanb.ttf",
        "cambriab.ttf",
        "arialbd.ttf",
        "segoeuib.ttf",
    )
    candidates = []
    if explicit is not None:
        candidates.append(explicit)

    for directory in _windows_font_directories():
        candidates.extend(directory / name for name in preferred_names)

    candidates.extend(
        [
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"),
            Path("/System/Library/Fonts/Supplemental/Georgia Bold.ttf"),
            Path("/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf"),
        ]
    )

    # Fonts shipped next to the template, so the project stays portable.
    template_dir = Path(__file__).resolve().parents[2] / "templates"
    if template_dir.is_dir():
        candidates.extend(sorted(template_dir.glob("*.ttf")))
        candidates.extend(sorted(template_dir.glob("*.otf")))

    return candidates


def resolve_font_path(explicit: Optional[Path] = None) -> Optional[Path]:
    """First usable font file, or ``None`` when nothing is available.

    Returning ``None`` is not fatal: Pillow falls back to its built-in bitmap
    font, which keeps the service working on a bare machine.
    """
    for candidate in _candidate_font_paths(explicit):
        if candidate.is_file():
            return candidate
    return None


def _clean_text(value: str) -> str:
    """Remove control characters that Pillow cannot measure or draw."""
    return "".join(char for char in value if char.isprintable()).strip()


class CertificateRenderer:
    """Draws recipient data onto the certificate template and exports a PDF."""

    def __init__(
        self,
        settings: Settings,
        layout: CertificateLayout = DEFAULT_LAYOUT,
    ) -> None:
        self.settings = settings
        self.layout = layout
        self.template_path = settings.certificate_template_path
        self.storage_dir = settings.certificate_storage_dir
        self._font_path = resolve_font_path(settings.font_path)

    # -- readiness ---------------------------------------------------------
    def is_ready(self) -> bool:
        """True when the template exists and is a readable image."""
        try:
            with Image.open(self.template_path) as image:
                image.verify()
        except Exception:  # noqa: BLE001 - any Pillow/OS error means "not ready"
            logger.error("Certificate template unusable: %s", self.template_path)
            return False
        return True

    def describe(self) -> str:
        """Human-readable summary used in startup logs."""
        font = self._font_path.name if self._font_path else "Pillow default font"
        return f"template={self.template_path.name} font={font} storage={self.storage_dir}"

    # -- rendering ---------------------------------------------------------
    def render(self, content: CertificateContent, destination: Path) -> Path:
        """Render ``content`` and write a PDF to ``destination``.

        Raises:
            CertificateRenderingError: if the template is missing or Pillow
                cannot draw/write the file. The message is client-safe.
        """
        if not self.template_path.is_file():
            raise CertificateRenderingError(
                f"Certificate template not found: {self.template_path.name}"
            )

        destination = Path(destination)
        ensure_directory(destination.parent)

        try:
            with Image.open(self.template_path) as source:
                image = source.convert("RGBA")
                canvas = ImageDraw.Draw(image)
                self._draw_fields(canvas, image.size, content)

                # Flatten transparency: PDF has no alpha channel.
                if image.mode != "RGB":
                    flattened = Image.new("RGB", image.size, (255, 255, 255))
                    flattened.paste(image, mask=image.split()[-1])
                    image = flattened

                # Write to a temporary file first, then swap it into place, so a
                # crash mid-write can never leave a half-written PDF that a
                # download request would happily serve.
                temporary = destination.parent / f"{destination.name}.tmp"
                try:
                    image.save(temporary, "PDF", resolution=PDF_RESOLUTION)
                    os.replace(temporary, destination)
                finally:
                    if temporary.exists():
                        temporary.unlink(missing_ok=True)
        except CertificateRenderingError:
            raise
        except Exception as exc:  # noqa: BLE001 - surfaced as a failed certificate
            logger.exception("Failed to render certificate %s", content.certificate_id)
            raise CertificateRenderingError(
                f"Could not render certificate ({type(exc).__name__})"
            ) from exc

        return destination

    def render_to_storage(self, content: CertificateContent) -> Path:
        """Render into the configured storage directory using the certificate ID."""
        destination = certificate_pdf_path(self.storage_dir, content.certificate_id)
        return self.render(content, destination)

    # -- internals ---------------------------------------------------------
    def _draw_fields(
        self,
        canvas: ImageDraw.ImageDraw,
        size: Tuple[int, int],
        content: CertificateContent,
    ) -> None:
        """Draw every configured field, centred, auto-fitted and overflow-safe."""
        width, height = size

        fields = (
            (content.recipient_name, self.layout.name),
            (content.course_name, self.layout.course),
            (content.footer_text(), self.layout.footer),
        )

        for raw_text, field in fields:
            text = _clean_text(raw_text)
            if not text:
                continue

            base_size = max(1, int(height * field.font_size_ratio))
            max_width = width * field.max_width_ratio
            font = self._fit_font(text, base_size, field.min_font_size, max_width)
            text = self._truncate_to_fit(canvas, text, font, max_width)

            canvas.text(
                (width * field.center_x_ratio, height * field.center_y_ratio),
                text,
                font=font,
                fill=field.color,
                anchor="mm",  # centre horizontally and vertically on the point
            )

    def _load_font(self, size: int) -> ImageFont.ImageFont:
        """Font object at ``size``; falls back to Pillow's built-in font."""
        if self._font_path is not None:
            try:
                return ImageFont.truetype(str(self._font_path), size)
            except OSError:  # pragma: no cover - unreadable font file
                logger.warning("Font unreadable, using default: %s", self._font_path)
                self._font_path = None
        return ImageFont.load_default(size)

    def _fit_font(
        self, text: str, base_size: int, min_size: int, max_width: float
    ) -> ImageFont.ImageFont:
        """Largest font size that keeps ``text`` within ``max_width``.

        This is what stops an unusually long recipient name from running off the
        edge of the template.
        """
        size = max(base_size, 1)
        font = self._load_font(size)
        while size > min_size and self._line_width(text, font) > max_width:
            size -= 1
            font = self._load_font(size)
        return font

    def _truncate_to_fit(
        self,
        canvas: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.ImageFont,
        max_width: float,
    ) -> str:
        """Last-resort guard: ellipsise text that cannot shrink any further."""
        if self._line_width(text, font) <= max_width:
            return text

        ellipsis = "…"
        truncated = text
        while truncated and self._line_width(truncated + ellipsis, font) > max_width:
            truncated = truncated[:-1]
        return (truncated.rstrip() + ellipsis) if truncated else ellipsis

    @staticmethod
    def _line_width(text: str, font: ImageFont.ImageFont) -> float:
        """Measured width of ``text`` in pixels."""
        try:
            return font.getlength(text)
        except AttributeError:  # very old Pillow
            return font.getsize(text)[0]
