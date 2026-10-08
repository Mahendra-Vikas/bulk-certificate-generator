# Certificate Alignment Tuning Guide

## Management Certificate Alignment

If the management team member's name is misaligned on the `CertificateManagement.jpeg`, use these environment variables to adjust:

### Position & Sizing

```powershell
# Vertical position (0 = top, 1 = bottom, default for mgmt: same as student)
$env:CERT_MGMT_NAME_Y_RATIO = "0.50"

# Vertical offset in pixels (positive = down, negative = up)
$env:CERT_MGMT_NAME_Y_OFFSET = "0"

# Horizontal margins (as ratio of width, default: 0.12)
$env:CERT_MGMT_NAME_MARGIN_RATIO = "0.12"

# Font size in pixels
$env:CERT_MGMT_NAME_FONT_SIZE = "80"

# Minimum font size before truncating
$env:CERT_MGMT_NAME_MIN_FONT_SIZE = "14"

# Text color (hex)
$env:CERT_MGMT_NAME_COLOR = "#000000"
```

### Example Adjustments

**Move text UP:** Decrease `CERT_MGMT_NAME_Y_RATIO` or use negative `CERT_MGMT_NAME_Y_OFFSET`
```powershell
$env:CERT_MGMT_NAME_Y_RATIO = "0.45"
# OR
$env:CERT_MGMT_NAME_Y_OFFSET = "-50"
```

**Move text DOWN:** Increase `CERT_MGMT_NAME_Y_RATIO` or use positive `CERT_MGMT_NAME_Y_OFFSET`
```powershell
$env:CERT_MGMT_NAME_Y_RATIO = "0.55"
# OR
$env:CERT_MGMT_NAME_Y_OFFSET = "50"
```

**Make text larger:**
```powershell
$env:CERT_MGMT_NAME_FONT_SIZE = "100"
```

**Make text smaller:**
```powershell
$env:CERT_MGMT_NAME_FONT_SIZE = "60"
```

### Testing

1. Set the environment variable
2. Restart the server: `uvicorn app.main:app --reload`
3. Generate a test certificate for a management member
4. Check the alignment in the PDF
5. Adjust and repeat until satisfied

## Student Certificate Alignment

Use similar variables without the `_MGMT_` part:

```powershell
$env:CERT_NAME_Y_RATIO = "0.52"
$env:CERT_NAME_Y_OFFSET = "0"
$env:CERT_NAME_FONT_SIZE = "80"
$env:CERT_NAME_COLOR = "#000000"
```

## Notes

- Management certificates inherit student settings if management-specific env vars are not set
- Changes require server restart to take effect
- Test with actual names from `management.csv` to see real alignment
- Delete generated PDFs in `certificates/` folder to force regeneration with new settings
