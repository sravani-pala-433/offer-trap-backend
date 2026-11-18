from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.core.schemas import (
    EvidenceUploadCompleteResponse,
    EvidenceUploadRequest,
    EvidenceUploadResponse,
    PublicReportResponse,
    ReportCreateRequest,
    ReportListResponse,
    ReportSubmissionResponse,
    SubmissionStatusResponse,
)
from app.services import evidence_service
from app.services import report_service
from app.utils.error_helpers import ServiceError


router = APIRouter(tags=["Reports and Evidence Uploads"])


@router.get("/reports", response_model=ReportListResponse)
def search_reports(
    query: Annotated[str, Query()] = "",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
    session: Session = Depends(get_db),
) -> dict[str, object]:
    return report_service.list_reports(session, query.strip(), page, page_size)


@router.get("/reports/{report_id}", response_model=PublicReportResponse)
def get_report(
    report_id: str,
    request: Request,
    response: Response,
    session: Session = Depends(get_db),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return report_service.get_report(
        session,
        report_id,
        lambda evidence_id: str(
            request.url_for(
                "get_public_report_evidence_chunk",
                report_id=report_id,
                evidence_id=evidence_id,
                chunk_index=0,
            )
        ).removesuffix("/chunks/0"),
    )


@router.get("/reports/{report_id}/status", response_model=SubmissionStatusResponse)
def get_report_status(
    report_id: str, response: Response, session: Session = Depends(get_db)
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return report_service.get_submission_status(session, report_id)


@router.post("/uploads", response_model=EvidenceUploadResponse, status_code=201)
def start_evidence_upload(
    request: EvidenceUploadRequest,
    session: Session = Depends(get_db),
) -> dict[str, object]:
    return evidence_service.initiate_upload(session, request)


@router.put("/uploads/{upload_id}/chunks/{chunk_index}", status_code=status.HTTP_204_NO_CONTENT)
async def upload_evidence_chunk(
    upload_id: str,
    chunk_index: int,
    request: Request,
    session: Session = Depends(get_db),
) -> Response:
    content_type = request.headers.get("content-type", "").split(";", maxsplit=1)[0].lower()
    if content_type != "application/octet-stream":
        raise ServiceError("Evidence chunks must use application/octet-stream.", 415)
    data = bytearray()
    async for part in request.stream():
        if len(data) + len(part) > evidence_service.UPLOAD_CHUNK_SIZE_BYTES:
            raise ServiceError("An evidence request chunk cannot exceed 4 MiB.", 413)
        data.extend(part)
    await run_in_threadpool(
        evidence_service.store_upload_chunk,
        session,
        upload_id,
        chunk_index,
        bytes(data),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/uploads/{upload_id}/complete",
    response_model=EvidenceUploadCompleteResponse,
)
def complete_evidence_upload(
    upload_id: str,
    session: Session = Depends(get_db),
) -> dict[str, str]:
    return evidence_service.complete_upload(session, upload_id)


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
    return report_service.create_report(session, request)


@router.get("/reports/{report_id}/evidence/{evidence_id}/chunks/{chunk_index}")
def get_public_report_evidence_chunk(
    report_id: str,
    evidence_id: str,
    chunk_index: int,
    session: Session = Depends(get_db),
) -> Response:
    _metadata, chunk = evidence_service.get_public_evidence(
        session, report_id, evidence_id, chunk_index
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
