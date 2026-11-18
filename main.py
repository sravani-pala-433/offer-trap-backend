import logging
import time
import uuid

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import RequestResponseEndpoint

from app.controllers.admin_controller import router as admin_router
from app.controllers.report_controller import router as report_router
from app.core.logging import bind_request_id, configure_logging, reset_request_id
from app.core.settings import settings
from app.utils.exception_handler import register_exception_handlers


configure_logging()
logger = logging.getLogger("offertrap.http")

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["X-Request-ID"],
)

app.include_router(report_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
register_exception_handlers(app)


@app.middleware("http")
async def log_http_requests(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    request_id = uuid.uuid4().hex
    request.state.request_id = request_id
    started_at = time.perf_counter()
    request_id_token = bind_request_id(request_id)

    try:
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started_at) * 1000
            logger.error(
                "http_request_failed method=%s path=%s duration_ms=%.2f",
                request.method,
                request.url.path,
                duration_ms,
            )
            raise
        duration_ms = (time.perf_counter() - started_at) * 1000
        response.headers["X-Request-ID"] = request_id

        log = logger.info if response.status_code < 400 else logger.warning
        if response.status_code >= 500:
            log = logger.error
        log(
            "http_request method=%s path=%s status=%d duration_ms=%.2f",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response
    finally:
        reset_request_id(request_id_token)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
