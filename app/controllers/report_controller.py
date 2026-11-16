from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.schemas import (
    PresignRequest,
    PresignResponse,
    ReportCreateRequest,
    ReportListResponse,
    ReportSubmissionResponse,
    SubmissionStatusResponse,
)
from app.services import report_service
from app.services.storage_service import get_storage_service
from app.utils.error_helpers import ServiceError


router = APIRouter(tags=["Reports and Evidence Uploads"])


@router.get("/reports", response_model=ReportListResponse)
def search_reports(
    query: Annotated[str, Query(max_length=200)] = "",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
    session: Session = Depends(get_db),
) -> dict[str, object]:
    return report_service.list_reports(session, query.strip(), page, page_size)


@router.get("/reports/{report_id}")
def get_report(report_id: str, session: Session = Depends(get_db)) -> dict[str, object]:
    return report_service.get_report(session, report_id)


@router.get("/reports/{report_id}/status", response_model=SubmissionStatusResponse)
def get_report_status(
    report_id: str, response: Response, session: Session = Depends(get_db)
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return report_service.get_submission_status(session, report_id)


@router.post("/uploads/presign", response_model=PresignResponse)
def presign_evidence_uploads(
    request: PresignRequest,
    session: Session = Depends(get_db),
) -> dict[str, object]:
    return report_service.create_presigned_uploads(
        session,
        request,
        get_storage_service(),
    )


@router.post(
    "/reports",
    response_model=ReportSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_report(
    request: ReportCreateRequest,
    response: Response,
    session: Session = Depends(get_db),
) -> dict[str, str]:
    if request.evidence_upload_ids and len(request.evidence_upload_ids) > 5:
        raise ServiceError("No more than five evidence files can be attached.", 422)
    response.headers["Cache-Control"] = "no-store"
    return report_service.create_report(session, request, get_storage_service())
