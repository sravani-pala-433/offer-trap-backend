import hmac
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.models import ModerationLog, Report
from app.core.schemas import AdminLoginRequest, ReportReviewRequest
from app.core.settings import settings
from app.repositories import admin_repository
from app.services import evidence_service
from app.utils.error_helpers import ServiceError
from app.utils.jwt_token import create_access_token
from app.utils.response_helpers import admin_report


logger = logging.getLogger(__name__)


def login(request: AdminLoginRequest) -> dict[str, Any]:
    configured_username = settings.admin_username
    configured_password = settings.admin_password
    if not configured_username or not configured_password:
        logger.error("admin_login_unavailable reason=missing_admin_credentials")
        raise ServiceError("Administrator login is not configured.", 503)
    if not settings.secret_key:
        logger.error("admin_login_unavailable reason=missing_secret_key")
        raise ServiceError("Administrator authentication is not configured.", 503)
    if len(settings.secret_key.get_secret_value()) < 32:
        logger.error("admin_login_unavailable reason=secret_key_too_short")
        raise ServiceError("SECRET_KEY must contain at least 32 characters.", 503)

    username_matches = hmac.compare_digest(
        request.username.strip().encode("utf-8"), configured_username.encode("utf-8")
    )
    password_matches = hmac.compare_digest(
        request.password.encode("utf-8"),
        configured_password.get_secret_value().encode("utf-8"),
    )
    if not (username_matches and password_matches):
        logger.warning("admin_login_failed reason=invalid_credentials")
        raise ServiceError("Invalid username or password.", 401)

    token, expires_at = create_access_token(configured_username)
    logger.info("admin_login_succeeded")
    return {"access_token": token, "token_type": "bearer", "expires_at": expires_at}


def list_reports(
    session: Session,
    *,
    status_filter: str | None,
    query: str,
    submitter_email: str | None,
) -> dict[str, list[dict[str, object]]]:
    reports = admin_repository.list_reports(
        session, status_filter, query.strip(), submitter_email
    )
    return {"items": [admin_report(report) for report in reports]}


def review_report(
    session: Session,
    report_id: str,
    request: ReportReviewRequest,
    moderator: str,
) -> dict[str, object]:
    try:
        report = admin_repository.get_report(session, report_id, lock=True)
        if report is None:
            raise ServiceError("Report not found.", 404)

        previous_status = report.review_status
        next_status = request.status
        if previous_status == "rejected":
            return admin_report(report)

        report.review_status = "rejected"
        report.is_public = False
        report.review_note = request.review_note
        report.reviewed_by = moderator
        report.reviewed_at = datetime.now(timezone.utc)
        admin_repository.add_moderation_log(
            session,
            ModerationLog(
                report_id=report.id,
                moderator=moderator,
                old_status=previous_status,
                new_status=next_status,
                note=request.review_note,
            ),
        )

        session.commit()
        session.refresh(report)
        session.expire(report, ["reward_entries"])
        logger.info(
            "moderation_decision report_id=%s old_status=%s new_status=%s",
            report.id,
            previous_status,
            next_status,
        )
        return admin_report(report)
    except Exception:
        session.rollback()
        raise


def delete_report(session: Session, report_id: str, moderator: str) -> None:
    try:
        report = admin_repository.get_report(session, report_id, lock=True)
        if report is None:
            raise ServiceError("Report not found.", 404)

        evidence_count = evidence_service.delete_report_evidence(report)
        session.delete(report)
        session.commit()
        logger.info(
            "admin_report_deleted report_id=%s moderator=%s evidence_files=%d",
            report_id,
            moderator,
            evidence_count,
        )
    except Exception:
        session.rollback()
        raise


def get_evidence_download(
    session: Session, evidence_id: str, chunk_index: int
) -> tuple[dict[str, Any], Any]:
    return evidence_service.get_admin_evidence(session, evidence_id, chunk_index)
