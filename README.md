# Bulk Certificate Generator

A FastAPI-based backend for generating and distributing personalized PDF certificates in bulk.

The system accepts a bulk generation request containing an event and a list of recipients, creates a persistent generation job, processes certificates in the background, tracks per-recipient progress and failures, and provides downloadable PDF certificates when generation is complete.

The project uses a predefined certificate template and stores job/certificate state in SQLite.

---

## Features

- **Bulk certificate generation** from a single API request
- **Background processing** so large requests return immediately
- **Persistent job tracking** using SQLite
- **Real-time progress reporting**
- **Per-recipient certificate status**
- **Failure isolation** — one failed recipient does not stop the remaining certificates
- **Automatic certificate ID generation**
- **PDF generation** using Pillow
- **Predefined certificate template**
- **Automatic text fitting** for long recipient names and course names
- **Secure certificate download**
- **Input validation** using Pydantic
- **Maximum batch-size protection**
- **102 automated tests**
- **Legacy CSV portal preserved** for compatibility with the original project

---

## Architecture

The application is organized into separate layers so that HTTP handling, business logic, database operations, and certificate rendering remain independent.

```text
                    Client
                      |
                      v
              FastAPI REST API
                      |
          +-----------+-----------+
          |                       |
          v                       v
     Job Routes            Certificate Routes
          |                       |
          v                       v
     JobService            CertificateService
          |                       |
          |                       v
          |                CertificateRenderer
          |                       |
          v                       v
       SQLite                  Pillow
          |                       |
          v                       v
    Job + Certificate       PDF Certificate
       records