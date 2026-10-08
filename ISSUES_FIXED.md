# Quick Fixes

## Issue 1: Management Certificate Name Misalignment - FIXED ✅

The code now supports management-specific positioning environment variables.

### How to Fix Alignment:

Stop the current server and set environment variables, then restart:

```powershell
# Example: Move name UP by 50 pixels
$env:CERT_MGMT_NAME_Y_OFFSET = "-50"

# Then restart server
uvicorn app.main:app --reload
```

**Common adjustments:**
- **Up**: Use negative `CERT_MGMT_NAME_Y_OFFSET` (e.g., -50, -100)
- **Down**: Use positive `CERT_MGMT_NAME_Y_OFFSET` (e.g., 50, 100)
- **Left/Right**: Adjust `CERT_MGMT_NAME_MARGIN_RATIO` (e.g., 0.15 for more margin)
- **Larger font**: Increase `CERT_MGMT_NAME_FONT_SIZE` (e.g., 100)
- **Smaller font**: Decrease `CERT_MGMT_NAME_FONT_SIZE` (e.g., 60)

**Delete old certificates** to force regeneration with new settings:
```powershell
Remove-Item certificates/*.pdf
```

---

## Issue 2: Student ID Verification - ALREADY WORKING ✅

The system **already asks for Student ID** before generating certificates:

### Current Flow (Student):
1. User enters **Name** (required)
2. User enters **Student ID** (required) ← Must match CSV
3. Backend verifies BOTH name + student ID
4. Only then generates certificate
5. Download starts

### Code validates:
- Frontend: Both fields marked `required` (HTML)
- Backend: `/verify` endpoint checks both fields exist
- CSV: `CSVHandler.find_student_by_name_and_id()` matches both

**This is working as intended.** The system will NOT generate a certificate without proper Student ID verification.

---

## Testing the Alignment

1. **Open browser:** http://localhost:8000
2. **Select Management tab**
3. **Enter name:** Dr. Rajesh Kumar
4. **Download certificate**
5. **Check PDF** - Is the name aligned correctly?
6. **If not aligned:**
   - Stop server (Ctrl+C)
   - Set env var: `$env:CERT_MGMT_NAME_Y_OFFSET = "-50"` (adjust value as needed)
   - Restart: `uvicorn app.main:app --reload`
   - Delete old cert: `Remove-Item certificates/CERT-MGMT-*.pdf`
   - Re-download and check

---

## Environment Variables Available

### Management-Specific (New!)
- `CERT_MGMT_NAME_Y_RATIO` - Vertical position (0.0 to 1.0)
- `CERT_MGMT_NAME_Y_OFFSET` - Vertical offset in pixels
- `CERT_MGMT_NAME_FONT_SIZE` - Font size
- `CERT_MGMT_NAME_COLOR` - Text color (hex)

### Student (Original)
- `CERT_NAME_Y_RATIO` - Vertical position
- `CERT_NAME_Y_OFFSET` - Vertical offset
- `CERT_NAME_FONT_SIZE` - Font size
- `CERT_NAME_COLOR` - Text color

**Note:** Management vars override student vars if set. Otherwise, it falls back to student settings.
