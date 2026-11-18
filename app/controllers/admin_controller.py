from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from fastapi.security import OAuth2PasswordRequestForm
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
    return admin_service.login(
        AdminLoginRequest(username=form_data.username, password=form_data.password)
    )


@router.get("/reports", response_model=AdminReportListResponse)
def list_admin_reports(
    response: Response,
    status_filter: Annotated[
        str | None,
        Query(alias="status", pattern="^(submitted|rejected)$"),
    ] = None,
    query: Annotated[str, Query()] = "",
    submitter_email: Annotated[str | None, Query()] = None,
    session: Session = Depends(get_db),
    _moderator: str = Depends(get_current_admin),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return admin_service.list_reports(
        session,
        status_filter=status_filter,
        query=query,
        submitter_email=submitter_email,
    )


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


@router.delete("/reports/{report_id}", status_code=204)
def delete_admin_report(
    report_id: str,
    session: Session = Depends(get_db),
    moderator: str = Depends(get_current_admin),
) -> Response:
    admin_service.delete_report(session, report_id, moderator)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.get("/evidence/{evidence_id}/chunks/{chunk_index}")
def download_admin_evidence_chunk(
    evidence_id: str,
    chunk_index: int,
    session: Session = Depends(get_db),
    _moderator: str = Depends(get_current_admin),
) -> Response:
    _metadata, chunk = admin_service.get_evidence_download(
        session,
        evidence_id,
        chunk_index,
    )
    return Response(
        content=chunk,
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-store",
            "Content-Length": str(len(chunk)),
            "X-Content-Type-Options": "nosniff",
        },
    )
