import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.core.models import ModerationLog, Report, utc_now
from app.core.schemas import ReportCreateRequest
from app.repositories import report_repository
from app.services import evidence_service
from app.utils.error_helpers import ServiceError
from app.utils.response_helpers import public_report, submission_status


logger = logging.getLogger(__name__)


def create_report(session: Session, request: ReportCreateRequest) -> dict[str, str]:
    try:
        uploads = report_repository.get_pending_uploads_for_update(
            session, request.evidence_upload_ids
        )
        if len(uploads) != len(request.evidence_upload_ids):
            raise ServiceError("One or more evidence uploads are invalid or already used.", 422)

        for upload in uploads:
            evidence_service.verify_ready_upload(upload)

        report = Report(
            company_name=request.company_name,
            recruiter_name=request.recruiter_name,
            recruiter_contact=request.recruiter_contact,
            job_title=request.job_title.strip() if request.job_title else None,
            job_url=request.job_url,
            category=request.category,
            description=request.description,
            payment_requested=request.payment_requested,
            submitter_name=request.contributor_username,
            submitter_email=str(request.contributor_email).lower(),
            is_anonymous=request.anonymous_attribution,
            review_status="submitted",
            is_public=True,
        )
        report_repository.add_report(session, report)

        for upload in uploads:
            upload.report_id = report.id
            upload.upload_status = "claimed"
            # Image bytes are private objects in Neon Object Storage; this row
            # retains metadata and the association with its report.
            upload.expires_at = utc_now()

        report_repository.add_moderation_log(
            session,
            ModerationLog(
                report_id=report.id,
                moderator="system",
                old_status=None,
                new_status="submitted",
                note="Report published on submission; it has not been independently verified.",
            ),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    logger.info("Report %s was submitted with %d evidence files", report.id, len(uploads))
    return {
        "id": report.id,
        "message": "Your report is now public. It has not been independently verified.",
        "status": "Published - unverified",
    }


def list_reports(session: Session, query: str, page: int, page_size: int) -> dict[str, object]:
    reports, total = report_repository.list_public_reports(session, query, page, page_size)
    return {
        "items": [public_report(report) for report in reports],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_report(
    session: Session,
    report_id: str,
    evidence_url: Callable[[str], str],
) -> dict[str, object]:
    report = report_repository.get_public_report(session, report_id)
    if report is None or not report.is_public:
        raise ServiceError("Report not found.", 404)
    result = public_report(report)
    if report.is_public and report.review_status != "rejected":
        result["description"] = report.description
        result["evidence"] = [
            {
                "id": evidence.id,
                "url": evidence_url(evidence.id),
                "content_type": evidence.content_type,
                "chunk_size_bytes": evidence_service.UPLOAD_CHUNK_SIZE_BYTES,
                "chunk_count": evidence_service.evidence_chunk_count(evidence.size_bytes),
            }
            for evidence in report.evidence_files
            if evidence.upload_status == "claimed"
            and evidence.content_type in evidence_service.PUBLIC_IMAGE_CONTENT_TYPES
            and evidence_service.evidence_chunks_are_complete(session, evidence)
        ]
    return result


def get_submission_status(session: Session, report_id: str) -> dict[str, Any]:
    report = report_repository.get_public_report(session, report_id)
    if report is None:
        raise ServiceError("Report not found.", 404)
    return submission_status(report)
