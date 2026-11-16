from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.schemas import (
    AdminLoginRequest,
    AdminLoginResponse,
    AdminReportListResponse,
    AdminReportResponse,
    ReportReviewRequest,
)
from app.services import admin_service
from app.services.storage_service import get_storage_service
from app.utils.error_helpers import ServiceError
from app.utils.jwt_token import get_current_admin


router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/login", response_model=AdminLoginResponse)
def admin_login(request: AdminLoginRequest, response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return admin_service.login(request)


@router.post("/token", response_model=AdminLoginResponse)
def swagger_admin_login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    response: Response,
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    if not (1 <= len(form_data.username) <= 120) or not (
        1 <= len(form_data.password) <= 1024
    ):
        raise ServiceError("Username or password has an invalid length.", 422)
    return admin_service.login(
        AdminLoginRequest(username=form_data.username, password=form_data.password)
    )


@router.get("/reports", response_model=AdminReportListResponse)
def list_admin_reports(
    response: Response,
    status_filter: Annotated[
        str | None,
        Query(
            alias="status",
            pattern="^(submitted|under_review|needs_information|approved|rejected)$",
        ),
    ] = None,
    query: Annotated[str, Query(max_length=200)] = "",
    session: Session = Depends(get_db),
    _moderator: str = Depends(get_current_admin),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return admin_service.list_reports(session, status_filter=status_filter, query=query)


@router.patch("/reports/{report_id}/status", response_model=AdminReportResponse)
def review_admin_report(
    report_id: str,
    request: ReportReviewRequest,
    response: Response,
    session: Session = Depends(get_db),
    moderator: str = Depends(get_current_admin),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return admin_service.review_report(session, report_id, request, moderator)


@router.get("/evidence/{evidence_id}")
def download_admin_evidence(
    evidence_id: str,
    response: Response,
    session: Session = Depends(get_db),
    _moderator: str = Depends(get_current_admin),
) -> StreamingResponse:
    response.headers["Cache-Control"] = "no-store"
    metadata, object_response = admin_service.get_evidence_download(
        session,
        evidence_id,
        get_storage_service(),
    )
    body = object_response["Body"]
    filename = str(metadata["name"]).replace("\r", "").replace("\n", "")
    fallback = "".join(character if character.isascii() and character.isalnum() else "_" for character in filename)
    disposition = f"attachment; filename=\"{fallback or 'evidence'}\"; filename*=UTF-8''{quote(filename, safe='')}"
    headers = {
        "Cache-Control": "no-store",
        "Content-Disposition": disposition,
        "Content-Length": str(metadata["size_bytes"]),
    }
    return StreamingResponse(
        body.iter_chunks(chunk_size=64 * 1024),
        media_type=str(metadata["content_type"]),
        headers=headers,
        background=BackgroundTask(body.close),
    )
