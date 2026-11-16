# OfferTrap backend

This backend contains OfferTrap's report submission, evidence storage, public
archive, review queue, administrator login, moderation history, and approval
reward ledger. It follows a controller → service → repository layout:

- `app/controllers` maps HTTP requests to typed service inputs.
- `app/services` applies workflow rules and coordinates storage and database work.
- `app/repositories` contains database queries and persistence operations.
- `app/core` contains configuration, schemas, database setup, and SQLAlchemy models.
- `app/utils` contains response serialization, authentication, and error handling.

## Configuration

Copy `.env.example` to `.env`, then set a PostgreSQL URL, a long random
`SECRET_KEY`, administrator credentials, and Backblaze B2 S3-compatible API credentials.
The application does not read or replace your existing `.env` automatically.
Set `B2_REGION` to the region shown in your bucket details. The endpoint is
derived as `https://s3.<region>.backblazeb2.com`; optionally set
`B2_ENDPOINT_URL` if you need to override it. Use a Backblaze application key
restricted to this bucket, not the account master key. The key needs read-files,
write-files, and delete-files capabilities for object inspection, promotion,
and temporary-upload cleanup.

Changing storage providers does not copy existing objects. If previous evidence
is still in R2, migrate those objects to B2 under the same object keys before
switching the running backend; otherwise downloads for those existing reports
will fail.

Keep the B2 bucket private. Configure its CORS policy to allow the frontend
origin, `PUT`, and the `Content-Type` request header. The presigned signature
binds the upload to the expected content type. A lifecycle rule for the
`pending/` prefix can remove abandoned uploads. The backend verifies uploaded
object size and content type before attaching it to a report; it sets no
application-level file-size limit.

## Database and local start

Install the dependencies, apply the initial schema migration, then start the
FastAPI app from this directory:

```powershell
python -m pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload
```

The API docs are available at `/api/docs`, and the health check is `/health`.
In Swagger, select **Authorize** and enter the administrator username and
password. The Swagger OAuth2 flow submits form data to `/api/v1/admin/token`;
the frontend's JSON login remains available at `/api/v1/admin/login`.

HTTP access logs include timestamp, level, source, request ID, method, path,
response status, and duration; application and error logs share that request
ID. Request bodies, query strings, usernames, passwords, and evidence contents
are not logged. The response includes `X-Request-ID` for correlating a client
report with server logs.

## Frontend connection

Set the frontend's `VITE_API_BASE_URL` to `http://localhost:8000/api/v1` and
`VITE_ADMIN_LOGIN_MOCK=false` to use the administrator login endpoint. Set
`FRONTEND_ORIGINS` to the comma-separated frontend origins that should call the
API. B2 itself also needs its own bucket CORS policy because uploads go directly
from the browser to B2.

## Moderation and privacy

The public archive returns every public report, but redacts the raw description,
recruiter contact, job URL, and reviewed summary until approval. Contributor
email is never included in public responses. The admin API requires a bearer
token, returns private report fields, and streams evidence through the backend.
Each status change is appended to `moderation_logs`.

An approval awards `REWARD_POINTS_PER_APPROVED_REPORT` points to that report's
submitter. The status endpoint reports points earned for that report. If an
approved report is later moved to another status, the ledger records a matching
reversal instead of deleting its history.

## API routes

- `GET /api/v1/reports` — public search and pagination.
- `GET /api/v1/reports/{id}` — public-safe report details.
- `GET /api/v1/reports/{id}/status` — submission status and reward points.
- `POST /api/v1/uploads/presign` — create short-lived direct-to-B2 upload URLs.
- `POST /api/v1/reports` — submit a report and claim verified uploads.
- `POST /api/v1/admin/login` — administrator login.
- `POST /api/v1/admin/token` — form-encoded login for Swagger's **Authorize** button.
- `GET /api/v1/admin/reports` — filter and search the moderation queue.
- `PATCH /api/v1/admin/reports/{id}/status` — approve, reject, or request information.
- `GET /api/v1/admin/evidence/{id}` — authenticated evidence download.
