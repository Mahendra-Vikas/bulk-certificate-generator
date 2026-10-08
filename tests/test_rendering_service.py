"""Rendering tests.

Pixel comparison would be brittle across fonts and Pillow versions, so these
tests assert on the parts that are contractual: the file produced, its format,
and the text handed to the drawing calls.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import List, Tuple

import pytest

from app.core.config import Settings
from app.services.rendering_service import (
    DEFAULT_LAYOUT,
    CertificateContent,
    CertificateRenderer,
    CertificateRenderingError,
    TextFieldLayout,
    resolve_font_path,
)


def content(**overrides) -> CertificateContent:
    values = {
        "recipient_name": "Aditya Singh",
        "course_name": "Computer Science",
        "event_name": "Python Workshop",
        "event_date": date(2026, 10, 8),
        "certificate_id": "CERT-2026-000001",
    }
    values.update(overrides)
    return CertificateContent(**values)


def make_renderer(settings: Settings) -> CertificateRenderer:
    return CertificateRenderer(settings)


# -- content ---------------------------------------------------------------
def test_footer_joins_event_date_and_certificate_id() -> None:
    assert content().footer_text() == "Python Workshop • 08 October 2026 • CERT-2026-000001"


def test_certificate_id_is_part_of_the_rendered_metadata() -> None:
    assert "CERT-2026-000042" in content(certificate_id="CERT-2026-000042").footer_text()


# -- layout ----------------------------------------------------------------
@pytest.mark.parametrize("field", ["name", "course", "footer"])
def test_layout_ratios_stay_inside_the_template(field: str) -> None:
    layout: TextFieldLayout = getattr(DEFAULT_LAYOUT, field)
    assert 0.0 < layout.center_x_ratio < 1.0
    assert 0.0 < layout.center_y_ratio < 1.0
    assert 0.0 < layout.max_width_ratio <= 1.0
    assert layout.font_size_ratio > 0
    assert layout.min_font_size > 0


# -- readiness -------------------------------------------------------------
def test_template_is_ready_when_readable(settings: Settings) -> None:
    assert make_renderer(settings).is_ready() is True


def test_template_is_not_ready_when_missing(settings: Settings) -> None:
    broken = Settings(
        database_url=settings.database_url,
        certificate_storage_dir=settings.certificate_storage_dir,
        certificate_template_path=Path("does-not-exist.png"),
        font_path=None,
    )
    assert CertificateRenderer(broken).is_ready() is False


def test_describe_mentions_the_template_and_storage(settings: Settings) -> None:
    description = make_renderer(settings).describe()
    assert settings.certificate_template_path.name in description
    assert str(settings.certificate_storage_dir) in description


# -- output ----------------------------------------------------------------
def test_render_writes_a_pdf_where_asked(settings: Settings, tmp_path: Path) -> None:
    destination = tmp_path / "out" / "certificate.pdf"
    written = make_renderer(settings).render(content(), destination)

    assert written == destination
    assert destination.is_file()
    assert destination.read_bytes().startswith(b"%PDF")


def test_render_to_storage_uses_the_certificate_id_as_the_file_name(
    settings: Settings,
) -> None:
    path = make_renderer(settings).render_to_storage(content(certificate_id="CERT-2026-000123"))

    assert path.name == "CERT-2026-000123.pdf"
    assert path.parent == settings.certificate_storage_dir
    assert path.is_file()


def test_render_raises_a_client_safe_error_without_a_template(settings: Settings) -> None:
    broken = Settings(
        database_url=settings.database_url,
        certificate_storage_dir=settings.certificate_storage_dir,
        certificate_template_path=settings.certificate_template_path.parent / "missing.png",
        font_path=None,
    )
    renderer = CertificateRenderer(broken)

    with pytest.raises(CertificateRenderingError) as error:
        renderer.render(content(), settings.certificate_storage_dir / "CERT-2026-000001.pdf")

    message = str(error.value)
    assert "missing.png" in message
    assert str(settings.certificate_template_path.parent) not in message


# -- what actually gets drawn ---------------------------------------------
def test_every_field_is_drawn(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    renderer = make_renderer(settings)
    drawn: List[Tuple[str, Tuple[int, int, int]]] = []

    def capture(this, point, text, **kwargs):
        drawn.append((text, kwargs.get("fill")))

    monkeypatch.setattr("PIL.ImageDraw.ImageDraw.text", capture)
    renderer.render(content(), settings.certificate_storage_dir / "CERT-2026-000001.pdf")

    texts = [text for text, _ in drawn]
    assert "Aditya Singh" in texts
    assert "Computer Science" in texts
    assert "Python Workshop • 08 October 2026 • CERT-2026-000001" in texts


def test_an_overlong_name_is_shrunk_to_fit(settings: Settings) -> None:
    """Auto-fit shrinks the font until either the name fits or the floor is hit."""
    renderer = make_renderer(settings)
    long_name = (
        "Aarav Shankar Krishnamurthy Venkatesan Balasubramanian Chidambaram "
        "Rajaraman Sundaram Parthasarathy Narayan"
    )
    base_size = max(1, int(600 * DEFAULT_LAYOUT.name.font_size_ratio))
    max_width = 800 * DEFAULT_LAYOUT.name.max_width_ratio
    floor = DEFAULT_LAYOUT.name.min_font_size

    font = renderer._fit_font(long_name, base_size, floor, max_width)
    width = renderer._line_width(long_name, font)

    # Either it fits, or the font has been shrunk all the way to the floor and
    # the truncation step is what guarantees the line stays inside the template.
    assert width <= max_width or renderer._line_width(
        long_name, renderer._load_font(floor)
    ) <= width + 1
    assert renderer._line_width(long_name, renderer._load_font(base_size)) > width


def test_a_normal_name_keeps_the_full_font_size(settings: Settings) -> None:
    renderer = make_renderer(settings)
    base_size = max(1, int(600 * DEFAULT_LAYOUT.name.font_size_ratio))
    max_width = 800 * DEFAULT_LAYOUT.name.max_width_ratio
    fitted = renderer._fit_font(
        "Aditya Singh", base_size, DEFAULT_LAYOUT.name.min_font_size, max_width
    )
    baseline = renderer._load_font(base_size)

    assert renderer._line_width("Aditya Singh", fitted) == renderer._line_width(
        "Aditya Singh", baseline
    )


def test_a_name_that_cannot_shrink_further_is_ellipsised(settings: Settings) -> None:
    """Even at the minimum size, text is never allowed to overflow."""
    renderer = make_renderer(settings)
    max_width = 800 * DEFAULT_LAYOUT.name.max_width_ratio
    huge = "Venkataramanan " * 20

    font = renderer._fit_font(huge, 120, DEFAULT_LAYOUT.name.min_font_size, max_width)
    result = renderer._truncate_to_fit(None, huge, font, max_width)

    assert result.endswith("…")
    assert renderer._line_width(result, font) <= max_width


def test_control_characters_are_stripped(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    renderer = make_renderer(settings)
    drawn: List[str] = []
    monkeypatch.setattr(
        "PIL.ImageDraw.ImageDraw.text",
        lambda self, point, text, **kwargs: drawn.append(text),
    )

    renderer.render(
        content(recipient_name="Adi\x00tya\x07 Singh"),
        settings.certificate_storage_dir / "control.pdf",
    )

    assert "Aditya Singh" in drawn


def test_blank_name_is_skipped_rather_than_drawn(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    renderer = make_renderer(settings)
    drawn: List[str] = []
    monkeypatch.setattr(
        "PIL.ImageDraw.ImageDraw.text",
        lambda self, point, text, **kwargs: drawn.append(text),
    )

    renderer.render(
        content(recipient_name="   "),
        settings.certificate_storage_dir / "blank.pdf",
    )

    assert "" not in [text.strip() for text in drawn]


# -- fonts -----------------------------------------------------------------
def test_a_font_is_found_on_this_machine_or_pillow_falls_back() -> None:
    resolved = resolve_font_path(None)
    assert resolved is None or resolved.is_file()


def test_renderer_falls_back_to_the_default_font(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    renderer = make_renderer(settings)
    renderer._font_path = None  # simulate "no usable font on this machine"

    path = renderer.render_to_storage(content(recipient_name="Fallback Font"))

    assert path.is_file()
