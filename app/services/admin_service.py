import hmac
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.models import ModerationLog, RewardLedger, Report
from app.core.schemas import AdminLoginRequest, ReportReviewRequest
from app.core.settings import settings
from app.repositories import admin_repository
from app.services.storage_service import B2StorageService
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
    session: Session, *, status_filter: str | None, query: str
) -> dict[str, list[dict[str, object]]]:
    reports = admin_repository.list_reports(session, status_filter, query.strip())
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
        if previous_status == next_status:
            if request.review_note is not None:
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
                logger.info(
                    "moderation_note_updated report_id=%s status=%s",
                    report.id,
                    previous_status,
                )
            return admin_report(report)

        report.review_status = next_status
        report.review_note = request.review_note
        report.reviewed_by = moderator
        report.reviewed_at = datetime.now(timezone.utc)
        if next_status == "approved":
            report.public_summary = request.public_summary or (
                f"A community report about {report.company_name} was reviewed and approved."
            )
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

        if next_status == "approved" and settings.reward_points_per_approved_report > 0:
            admin_repository.add_reward_entry(
                session,
                RewardLedger(
                    report_id=report.id,
                    points=settings.reward_points_per_approved_report,
                    event_type="award",
                    moderator=moderator,
                ),
            )
        elif previous_status == "approved" and next_status != "approved":
            current_balance = sum(entry.points for entry in report.reward_entries)
            if current_balance > 0:
                admin_repository.add_reward_entry(
                    session,
                    RewardLedger(
                        report_id=report.id,
                        points=-current_balance,
                        event_type="reversal",
                        moderator=moderator,
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


def get_evidence_download(
    session: Session, evidence_id: str, storage: B2StorageService
) -> tuple[dict[str, Any], dict[str, Any]]:
    evidence = admin_repository.get_evidence(session, evidence_id)
    if evidence is None:
        raise ServiceError("Evidence file not found.", 404)
    object_response = storage.open_object(evidence.object_key)
    return {
        "name": evidence.original_name,
        "content_type": evidence.content_type,
        "size_bytes": evidence.size_bytes,
    }, object_response
