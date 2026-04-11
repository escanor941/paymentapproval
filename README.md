# Factory Purchase Approval System (Render Cloud Ready)

Web-based, mobile-friendly purchase approval system for factory and office users.
This project is prepared for Render deployment with PostgreSQL and HTTPS.

## Stack
- Backend + frontend hosting: FastAPI (Jinja templates + Bootstrap + JS)
- Database: PostgreSQL in Render (SQLite fallback for local dev)
- Exports: Excel and PDF
- Uploads: Local disk (Render persistent disk) or S3-compatible cloud storage

## Core Features
- Factory mobile users submit local purchase requests
- Admin dashboard for approval and payment tracking
- Approve, Reject, Hold, Mark Paid (with partial payment)
- Live status updates via polling
- Reports and filters (daily/weekly/monthly/vendor/item/factory/user/payment)
- Export report to Excel or PDF
- Mobile-responsive UI with role-based login

## Default Users
- Admin: admin / admin123
- Factory: factory1 / factory123

## Project Structure
```text
app/
  main.py
  migrate.py
  database.py
  models.py
  security.py
  routers/
    auth.py
    pages.py
    requests.py
    reports.py
    masters.py
  templates/
  static/
  utils/
    storage.py
requirements.txt
render.yaml
start.sh
.env.example
schema.sql
```

## Environment Variables
Use these on Render (or in local .env file):

- SESSION_SECRET: strong random secret for session signing
- SESSION_HTTPS_ONLY: true in production
- DATABASE_URL: Render PostgreSQL connection string
- AUTO_CREATE_SCHEMA: true/false (default true)
- STORAGE_BACKEND: local or s3
- UPLOAD_DIR: local upload path (default uploads)
- RENDER_DISK_MOUNT_PATH: set automatically when using Render persistent disk

### Optional S3-Compatible Variables (when STORAGE_BACKEND=s3)
- S3_ENDPOINT_URL
- S3_BUCKET
- S3_REGION
- S3_ACCESS_KEY
- S3_SECRET_KEY
- S3_PUBLIC_BASE_URL

## Local Run
1. Create and activate virtual environment.
2. Install dependencies:
```powershell
python -m pip install -r requirements.txt
```
3. Run migration/bootstrap:
```powershell
python -m app.migrate
```
4. Start app:
```powershell
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Render Deployment Guide
1. Push this project to a Git repository.
2. Create a new Render PostgreSQL instance.
3. In Render, create a new Web Service from your repo.
4. Build command:
```bash
pip install -r requirements.txt
```
5. Start command:
```bash
bash start.sh
```
6. Set environment variables:
   - DATABASE_URL = Render Postgres Internal URL
   - SESSION_SECRET = strong random value
   - SESSION_HTTPS_ONLY = true
   - AUTO_CREATE_SCHEMA = true
   - STORAGE_BACKEND = local or s3
7. Optional but recommended for local uploads on Render:
   - Add persistent disk mounted at /var/data
   - Set UPLOAD_DIR=/var/data/uploads
8. Deploy and open public HTTPS URL from Render dashboard.

## Database Migration Steps

### Current bootstrap migration
This project uses SQLAlchemy metadata migration bootstrap:
```bash
python -m app.migrate
```
This creates missing tables and seeds default data.

### Recommended production workflow
1. Set AUTO_CREATE_SCHEMA=false after initial deployment.
2. Run migration command manually during release:
```bash
python -m app.migrate
```
3. For advanced versioned migrations later, introduce Alembic and migrate from current schema baseline.

## Render Notes for Uploads
- Local upload mode with no persistent disk is ephemeral on Render restart/redeploy.
- Use either:
  - Render persistent disk (simple)
  - S3-compatible storage (best for scale and reliability)

## Health Check
- GET /health returns {"status":"ok"}

## Required API Endpoints
- POST /login
- POST /requests
- GET /requests
- PUT /requests/{id}
- DELETE /requests/{id}
- POST /requests/{id}/approve
- POST /requests/{id}/reject
- POST /requests/{id}/pay
- GET /reports/daily
- GET /reports/monthly
- GET /masters/vendors
