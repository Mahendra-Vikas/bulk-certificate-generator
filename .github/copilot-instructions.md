# Copilot instructions (certificate-project)

## Big picture
- This is a small FastAPI app that serves a static HTML portal and generates downloadable PDF certificates on-demand.
- Data source is a CSV export from a workshop attendance form; there is no database.

## Key files / responsibilities
- [app/main.py](app/main.py): FastAPI app + HTTP API, instantiates `CSVHandler` and `CertificateGenerator` as globals.
- [app/csv_handler.py](app/csv_handler.py): reads the workshop CSV and finds a student by **name + Student_Id**.
- [app/certificate_generator.py](app/certificate_generator.py): uses Pillow to render the student name onto a template image and save a PDF to `certificates/`.
- [templates/index.html](templates/index.html): static frontend that calls `/verify` then redirects to `/certificate`.
- [setup_template.py](setup_template.py): one-time script that generates `templates/certificate_template.jpg`.

## Data flow (request → PDF)
1. User submits name + student ID in the frontend ([templates/index.html](templates/index.html)).
2. Backend verifies via `CSVHandler.find_student_by_name_and_id(name, student_id)`.
3. Backend derives `certificate_id` using `CSVHandler.generate_certificate_id(student_id)` (format: `CERT-WORKSHOP1-{student_id}`).
4. If `certificates/{certificate_id}.pdf` does not exist, generate it with `CertificateGenerator.generate_certificate(student_name, certificate_id)`.
5. Return the PDF via `FileResponse`.

## API conventions (important: these are query-param endpoints)
- `/verify?name=...&student_id=...` and `/certificate?name=...&student_id=...` are the current shapes (not path params).
- `/generate-all?admin_key=...` bulk-generates PDFs for all rows in the CSV.

## CSV conventions / gotchas
- Default CSV path is `data/Workshop-I Attendance Form (Responses).csv` (see [app/csv_handler.py](app/csv_handler.py)).
- Expected column names are workshop-style: `Name`, `Student_Id`, `Email_id`, `Course`, `Code`.
- Name matching is case-insensitive; student ID matching is exact after `.strip()`.
- There is an older `data/students.csv` with different columns; treat it as legacy unless you also update the handler.

## Dev workflows (Windows-friendly)
- Install deps: `pip install -r requirements.txt`
- Generate template (if missing): `python setup_template.py`
- Run server: `uvicorn app.main:app --reload` (defaults to port 8000)

## Deployment / env vars
- Render deploy config lives in [render.yaml](render.yaml) and passes env vars consumed by [app/main.py](app/main.py).
- Certificate name placement is tunable via env vars read in [app/certificate_generator.py](app/certificate_generator.py): `CERT_NAME_Y_RATIO`, `CERT_NAME_Y_OFFSET`, `CERT_NAME_FONT_SIZE`, `CERT_FONT_PATH`, etc.

## Project-specific patterns
- Keep filesystem paths relative to repo root (template path `templates/...`, output `certificates/...`).
- Certificate PDFs are cached by filename; if behavior changes, delete the corresponding file in `certificates/` to force regeneration.
- The rendered certificate currently writes **only the student name** onto the template; the `certificate_id` is used for the PDF filename only.

## When changing behavior
- If you change endpoint shapes or query parameters, also update the JS fetch/redirect logic in [templates/index.html](templates/index.html).
- If you change CSV columns or source file, update `CSVHandler` and ensure `validate_csv_structure()` matches the new headers.