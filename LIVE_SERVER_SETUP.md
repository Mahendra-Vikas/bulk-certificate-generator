# Live Server Setup Guide

## Problem Solved
Fixed issues with running the HTML file in VS Code Live Server while the FastAPI backend runs on `http://127.0.0.1:8000`.

### Issues That Were Fixed:
1. **Images not loading** - The HTML was trying to fetch images from relative paths that don't exist on Live Server port
2. **Certificates not generating** - The API calls were going to the wrong server (Live Server port instead of FastAPI port 8000)
3. **CORS errors** - Requests from Live Server weren't reaching the FastAPI backend

## Solution: Dynamic API Base URL

The `index.html` file now automatically detects your server setup:

- **If accessing via FastAPI directly** (`http://127.0.0.1:8000`):
  - Uses relative paths (e.g., `/verify`, `/certificate`, `/static/logo.jpg`)
  - All requests go directly to FastAPI

- **If accessing via Live Server** (e.g., `http://localhost:5500` or another port):
  - Automatically routes API calls to `http://127.0.0.1:8000`
  - Uses `http://127.0.0.1:8000/static/` for image URLs
  - Uses `http://127.0.0.1:8000/verify` for API endpoints

## How to Use

### Option 1: Access directly via FastAPI (Recommended)
```
Open browser: http://127.0.0.1:8000
```
✅ Everything works with relative paths
✅ No CORS issues
✅ Images load from `/static/`

### Option 2: Use VS Code Live Server
1. Right-click on `templates/index.html`
2. Click "Open with Live Server"
3. Browser opens (usually on `http://localhost:5500` or similar)
4. The app automatically detects this and routes requests to `http://127.0.0.1:8000`

✅ Images load via absolute URLs
✅ API calls routed to correct backend
✅ No manual configuration needed

## What Changed

**File Modified:** `templates/index.html`

Added auto-detection at the top of the JavaScript section:
```javascript
const getApiBaseUrl = () => {
    const currentHost = window.location.hostname;
    const currentPort = window.location.port;

    if ((currentHost === 'localhost' || currentHost === '127.0.0.1') && currentPort === '8000') {
        return '';  // Use relative paths
    }

    return 'http://127.0.0.1:8000';  // Use absolute URL for external servers
};

const API_BASE = getApiBaseUrl();
```

All API calls and static file references now use `${API_BASE}` prefix.

## Troubleshooting

### Server not running?
```powershell
D:/certificate-distribution-platform2/.venv/Scripts/python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Images still not loading?
1. Verify FastAPI is running on port 8000
2. Check that `templates/` directory has: `logo.jpg`, `co-dev_logo.png`, `certificate_template.jpg`, `CertificateManagement.jpeg`
3. Verify browser console (F12) for specific error messages

### Certificates not generating?
1. Check that `students.csv` and `management.csv` exist in the project root
2. Verify the names and IDs match exactly (case-sensitive for names, exact match for IDs)
3. Check that the `certificates/` directory exists and is writable

### Still getting errors?
Open browser console (F12 → Console) and look for:
- Network errors → Check if FastAPI is running on 8000
- CORS errors → The API_BASE detection may need adjustment
- Missing files → Check file paths in the error messages
