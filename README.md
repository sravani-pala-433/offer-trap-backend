# OfferTrap backend

FastAPI service for report submission, public report details, administrator
moderation, and evidence images. Neon PostgreSQL stores report and
evidence metadata; Neon Object Storage stores the image bytes.

## Evidence storage

Create a private [Neon Object Storage](https://neon.com/blog/building-neon-object-storage)
bucket for the project/branch, then set
`AWS_ENDPOINT_URL_S3`, `AWS_REGION`, `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, and `NEON_STORAGE_BUCKET` in the backend environment.
The four `AWS_*` values are supplied by Neon for the branch; do not expose them
to the frontend. PostgreSQL keeps only an evidence object-key prefix and its
metadata. The bucket stays private: public image reads for published reports and
authenticated admin downloads are proxied through the backend.

The frontend has no application-level total file-size cap. Uploads are divided
into 4 MiB requests because Vercel Functions limit an individual request body
to 4.5 MB; the backend writes each 4 MiB request as an object in Neon Object
Storage. Reads use 4 MiB chunks too, and the frontend reassembles them for
display/download. This is server-mediated (the browser never receives a
presigned storage URL); Neon Object Storage, rather than Postgres, holds the
image bytes. Neon's [current Free plan details](https://neon.com/blog/neon-free-plan-1-gb-per-project)
list 5 GB of Object Storage per project; check Neon's pricing/usage page for
current limits and costs.

Run the cleanup script periodically (for example, hourly) to delete abandoned
unclaimed uploads after `EVIDENCE_UPLOAD_TTL_MINUTES`:

```powershell
python scripts/cleanup_expired_uploads.py
```

## Database migrations

The schema is defined in one initial migration at
`migrations/versions/0001_offertrap_initial.py`. It uses the short revision ID
`1`. The migration widens Alembic's PostgreSQL `version_num` tracking column to
`TEXT`, avoiding its default `VARCHAR(32)` cap; keep future revision IDs numeric
and short (for example, `2`, `3`) for readability. Since the database tables
have been dropped, run this against the empty database:

```powershell
alembic upgrade head
```

This consolidated migration is for a fresh database. If an `alembic_version`
table still contains an older revision ID, Alembic will not recognize it after
the old migration files are removed; confirm that table is empty before
upgrading.

## Configuration and local start

Copy `.env.example` to `.env`, set the Neon PostgreSQL `DATABASE_URL`, a random
`SECRET_KEY` with at least 32 characters, administrator credentials, and the
frontend origins allowed to call the API. Do not commit `.env`.

```powershell
python -m pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload
```

The API docs are available at `/api/docs`, and the health check is `/health`.
Swagger admin login uses **Authorize** and posts form data to
`/api/v1/admin/token`; the frontend's JSON login uses `/api/v1/admin/login`.
`FRONTEND_ORIGINS` must include each deployed frontend origin and local
development origin. Evidence requests go to this API, which communicates with
Neon Object Storage using server-side credentials.

## Upload an image with the script

From this directory, upload one JPEG, PNG, or WEBP image through the backend and
store it in Neon Object Storage through the backend:

```powershell
python scripts/upload_evidence.py "C:\path\to\evidence.png"
```

The default API base is `http://localhost:8000/api/v1`. To use a deployed API:

```powershell
python scripts/upload_evidence.py "C:\path\to\evidence.png" --api-base https://your-backend-domain/api/v1
```

Add `--submit-report` to enter report fields interactively and create a real
report after the image upload. Use a local or staging database while testing:

```powershell
python scripts/upload_evidence.py "C:\path\to\evidence.png" --submit-report
```

Without `--submit-report`, the image remains an unclaimed upload until its
expiry and is removed from Neon Object Storage by the cleanup script. The script
sends each 4 MiB chunk to the backend; it does not contact storage directly or
require browser CORS.

## Moderation and privacy

New reports are published immediately with status `submitted` (shown as
`Published - unverified`). Their description, recruiter contact, optional job
URL, and attached images are public. The submitter name is public unless they
selected anonymous attribution; their email is always private. An administrator
can reject an entire report, which hides the report and all of its evidence from
public routes. Evidence is not individually approved or rejected. Admin
endpoints require a bearer token and expose the private fields needed for review.

This workflow has no approval or verification action, so it does not award
reward points. The legacy reward ledger table remains for data compatibility;
a separate reward policy is needed before credits can be issued.

HTTP access logs include timestamp, level, source, request ID, method, path,
response status, and duration. Request bodies, query strings, credentials, and
evidence contents are not logged. Responses include `X-Request-ID` for
correlating a client report with server logs.

## API routes

- `GET /api/v1/reports` — public search and pagination.
- `GET /api/v1/reports/{id}` — public-safe report details.
- `GET /api/v1/reports/{id}/status` — whether the report remains published or was rejected.
- `POST /api/v1/uploads` — initialize a chunked backend upload.
- `PUT /api/v1/uploads/{upload_id}/chunks/{index}` — write one image chunk.
- `POST /api/v1/uploads/{upload_id}/complete` — verify and finalize an upload.
- `POST /api/v1/reports` — submit a report and claim completed uploads.
- `GET /api/v1/reports/{id}/evidence/{evidence_id}/chunks/{index}` — published report image chunk.
- `POST /api/v1/admin/login` — administrator login.
- `POST /api/v1/admin/token` — form-encoded login for Swagger's **Authorize** button.
- `GET /api/v1/admin/reports` — filter by status, search, or exact submitter email (`submitter_email`).
- `PATCH /api/v1/admin/reports/{id}/status` — reject a whole report.
- `GET /api/v1/admin/evidence/{id}/chunks/{index}` — authenticated evidence chunk.
