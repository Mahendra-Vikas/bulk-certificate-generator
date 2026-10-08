"""Certificate Generator Module.

Generates personalized certificates by drawing names onto template images using Pillow.
Simple, straightforward approach: load font → set position → draw text → save PDF.
"""

import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


class CertificateGenerator:
    """Generate personalized certificates from template images and export as PDF."""

    def __init__(self, template_path: str = "templates/certificate_template.jpg",
                 output_dir: str = "certificates",
                 management_template_path: str = "templates/CertificateManagement.jpeg"):
        """Initialize certificate generator.

        Args:
            template_path: Path to student certificate template
            output_dir: Directory for output PDFs
            management_template_path: Path to management certificate template
        """
        project_root = Path(__file__).resolve().parents[1]
        self._project_root = project_root

        # Resolve template paths
        self.template_path = self._resolve_path(template_path, project_root)
        self.management_template_path = self._resolve_path(management_template_path, project_root)

        # Setup output directory
        self.output_dir = str(project_root / output_dir)
        os.makedirs(self.output_dir, exist_ok=True)

    def _resolve_path(self, path_str: str, project_root: Path) -> str:
        """Resolve a path relative to project root."""
        candidate = Path(path_str.replace("\\", "/"))
        if not candidate.is_absolute():
            candidate = project_root / candidate
        return str(candidate)

    def _resolve_font_path(self) -> str:
        """Resolve font path from environment or use system fonts."""
        # Try environment variable first
        env_font = (os.getenv("CERT_FONT_PATH") or "").strip()
        if env_font:
            p = Path(env_font.replace("\\", "/"))
            if not p.is_absolute():
                p = self._project_root / p
            if p.exists():
                return str(p)

        # Try project templates folder
        candidates = [
            self._project_root / "templates" / "DejaVuSans-Bold.ttf",
            self._project_root / "templates" / "DejaVuSans.ttf",
        ]
        for c in candidates:
            if c.exists():
                return str(c)

        # Try system paths
        system_paths = [
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        for font_path in system_paths:
            if Path(font_path).exists():
                return font_path

        # Try font names directly
        for name in ["arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"]:
            try:
                ImageFont.truetype(name, 12)
                return name
            except:
                continue

        raise RuntimeError("No TrueType font found. Install a .ttf file in templates/ or set CERT_FONT_PATH.")

        raise RuntimeError("No TrueType font found. Install a .ttf file in templates/ or set CERT_FONT_PATH.")

    def generate_certificate(self, student_name: str, certificate_id: str, course: str = None) -> str:
        """Generate a student certificate.

        Args:
            student_name: Name to write on certificate
            certificate_id: ID for output filename (e.g., "John_Doe")
            course: Unused (kept for compatibility)

        Returns:
            Path to generated PDF
        """
        if not os.path.exists(self.template_path):
            raise FileNotFoundError(f"Template not found: {self.template_path}")

        # Open template
        with Image.open(self.template_path) as img_in:
            img = img_in.convert("RGBA")
            draw = ImageDraw.Draw(img)
            width, height = img.size

        # Load font
        font_path = self._resolve_font_path()
        font_size = int(os.getenv("CERT_NAME_FONT_SIZE", "70"))
        font = ImageFont.truetype(font_path, size=font_size)

        # Get position
        cert_x = os.getenv("CERT_NAME_X")
        cert_y = os.getenv("CERT_NAME_Y")

        if cert_x and cert_y:
            x, y = float(cert_x), float(cert_y)
        else:
            # Default hard-coded position for students
            x, y = 250, 550

        # Get color
        color_hex = (os.getenv("CERT_NAME_COLOR", "#000000") or "#000000").strip()
        if color_hex.startswith("#") and len(color_hex) >= 7:
            r = int(color_hex[1:3], 16)
            g = int(color_hex[3:5], 16)
            b = int(color_hex[5:7], 16)
            a = int(color_hex[7:9], 16) if len(color_hex) == 9 else 255
            name_color = (r, g, b, a)
        else:
            name_color = (0, 0, 0, 255)

        # Draw name
        draw.text((x, y), student_name.strip(), font=font, fill=name_color)

        # Convert to RGB and save as PDF
        if img.mode != "RGB":
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1])
            img = background

        output_path = os.path.join(self.output_dir, f"{certificate_id}.pdf")
        img.save(output_path, "PDF", resolution=300.0)

        return output_path

    def certificate_exists(self, certificate_id: str) -> bool:
        """
        Check if certificate already exists

        Args:
            certificate_id: Certificate ID to check

        Returns:
            True if certificate exists, False otherwise
        """
        if not self.output_dir:
            return False

        output_path = os.path.join(self.output_dir, f"{certificate_id}.pdf")
        return os.path.exists(output_path)

    def get_certificate_path(self, certificate_id: str) -> str:
        """
        Get the path to a certificate

        Args:
            certificate_id: Certificate ID

        Returns:
            Path to the certificate PDF
        """
        if not self.output_dir:
            raise RuntimeError("Output directory is not configured")

        return os.path.join(self.output_dir, f"{certificate_id}.pdf")

    def generate_management_certificate(self, person_name: str, certificate_id: str) -> str:
        """
        Generate a management certificate (name only, no course)

        Args:
            person_name: The person's name
            certificate_id: Certificate ID for the filename

        Returns:
            Path to the generated PDF certificate
        """
        if not self.output_dir:
            raise RuntimeError("Output directory is not configured")

        # Use management template if available, otherwise use regular template
        template = self.management_template_path or self.template_path

        if not os.path.exists(template):
            raise FileNotFoundError(f"Template image not found: {template}")

        output_filename = f"{certificate_id}.pdf"
        output_path = os.path.join(self.output_dir, output_filename)

        with Image.open(template) as img_in:
            img = img_in.convert("RGBA")
            draw = ImageDraw.Draw(img)

            # Get font
            font_path = self._resolve_font_path()
            font_size = int(os.getenv("CERT_MGMT_NAME_FONT_SIZE", "55"))
            font = ImageFont.truetype(font_path, size=font_size)

            # Get color
            color_hex = (os.getenv("CERT_MGMT_NAME_COLOR", os.getenv("CERT_NAME_COLOR", "#000000")) or "#000000").strip()
            if color_hex.startswith("#") and len(color_hex) in (7, 9):
                r = int(color_hex[1:3], 16)
                g = int(color_hex[3:5], 16)
                b = int(color_hex[5:7], 16)
                a = int(color_hex[7:9], 16) if len(color_hex) == 9 else 255
                name_color = (r, g, b, a)
            else:
                name_color = (0, 0, 0, 255)

            # Get position - use absolute coordinates (600, 500 for management)
            cert_mgmt_x = os.getenv("CERT_MGMT_NAME_X", "600")
            cert_mgmt_y = os.getenv("CERT_MGMT_NAME_Y", "500")

            x, y = float(cert_mgmt_x), float(cert_mgmt_y)

            # Draw name directly at position
            name = (person_name or "").strip()
            if not name:
                raise ValueError("Person name is empty")

            draw.text((x, y), name, font=font, fill=name_color)

            if img.mode != "RGB":
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[-1])
                out_img = background
            else:
                out_img = img

            out_img.save(output_path, "PDF", resolution=300.0)

        return output_path
