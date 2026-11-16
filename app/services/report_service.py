import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.models import EvidenceFile, ModerationLog, Report, utc_now
from app.core.schemas import PresignFileRequest, PresignRequest, ReportCreateRequest
from app.core.settings import settings
from app.repositories import report_repository
from app.services.storage_service import B2StorageService
from app.utils.error_helpers import ServiceError
from app.utils.response_helpers import public_report, submission_status


logger = logging.getLogger(__name__)

CONTENT_TYPES_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
SAFE_FILENAME_PATTERN = re.compile(r"[^\w .()\-]", re.UNICODE)


def _normalize_filename(filename: str) -> tuple[str, str, str]:
    filename = filename.replace("\\", "/").split("/")[-1].strip()
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    extension = f".{extension}"
    expected_type = CONTENT_TYPES_BY_EXTENSION.get(extension)
    if not expected_type:
        raise ServiceError("Only JPEG, PNG, WEBP, PDF, DOC, and DOCX evidence is supported.", 422)

    safe_name = SAFE_FILENAME_PATTERN.sub("_", filename).strip(" .")[:255]
    if not safe_name:
        safe_name = f"evidence{extension}"
    return safe_name, extension, expected_type


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _upload_plan(
    item: PresignFileRequest, storage: B2StorageService
) -> tuple[EvidenceFile, dict[str, object]]:
    filename, extension, expected_type = _normalize_filename(item.filename)
    declared_type = item.content_type.split(";", maxsplit=1)[0].strip().lower()
    if declared_type not in {expected_type, "application/octet-stream"}:
        raise ServiceError("The selected file extension does not match its file type.", 422)

    upload_id = str(uuid.uuid4())
    object_key = f"pending/{upload_id}/{uuid.uuid4().hex}{extension}"
    expires_at = utc_now() + timedelta(seconds=settings.b2_presigned_url_ttl_seconds)
    record = EvidenceFile(
        id=upload_id,
        original_name=filename,
        object_key=object_key,
        content_type=expected_type,
        size_bytes=item.size_bytes,
        upload_status="pending",
        expires_at=expires_at,
    )
    response = {
        "upload_id": upload_id,
        "upload_url": storage.create_upload_url(object_key, expected_type),
        "method": "PUT",
        "headers": {"Content-Type": expected_type},
        "expires_at": expires_at,
    }
    return record, response


def create_presigned_uploads(
    session: Session, request: PresignRequest, storage: B2StorageService
) -> dict[str, list[dict[str, object]]]:
    records: list[EvidenceFile] = []
    response_items: list[dict[str, object]] = []
    try:
        for item in request.files:
            record, response_item = _upload_plan(item, storage)
            records.append(record)
            response_items.append(response_item)
        report_repository.add_pending_uploads(session, records)
        session.commit()
    except Exception:
        session.rollback()
        raise

    logger.info("evidence_upload_urls_created count=%d", len(records))
    return {"uploads": response_items}


def _verify_uploaded_file(
    record: EvidenceFile, storage: B2StorageService
) -> str:
    if _utc_datetime(record.expires_at) <= utc_now():
        raise ServiceError("An evidence upload has expired. Please upload the file again.", 422)

    metadata = storage.inspect_object(record.object_key)
    if metadata is None:
        raise ServiceError("An evidence file has not finished uploading.", 422)
    actual_size = int(metadata.get("ContentLength", -1))
    actual_type = str(metadata.get("ContentType", "")).split(";", maxsplit=1)[0].strip().lower()
    if actual_size != record.size_bytes or actual_type != record.content_type.lower():
        raise ServiceError("Uploaded evidence does not match its declared file details.", 422)
    etag = metadata.get("ETag")
    if not etag:
        raise ServiceError("Could not securely verify the uploaded evidence.", 422)

    extension = record.original_name.rsplit(".", 1)[-1].lower()
    prefix = storage.read_object_prefix(record.object_key)
    valid_signature = {
        "pdf": prefix.startswith(b"%PDF-"),
        "png": prefix.startswith(b"\x89PNG\r\n\x1a\n"),
        "jpg": prefix.startswith(b"\xff\xd8\xff"),
        "jpeg": prefix.startswith(b"\xff\xd8\xff"),
        "webp": len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP",
        "doc": prefix.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
        "docx": prefix.startswith(b"PK\x03\x04") and b"word/" in prefix,
    }.get(extension, False)
    if not valid_signature:
        raise ServiceError("The evidence content does not match its file extension.", 422)
    return str(etag)


def create_report(
    session: Session, request: ReportCreateRequest, storage: B2StorageService
) -> dict[str, str]:
    promoted_keys: list[str] = []
    temporary_keys: list[str] = []
    source_etags: dict[str, str] = {}
    try:
        uploads = report_repository.get_pending_uploads_for_update(
            session, request.evidence_upload_ids
        )
        if len(uploads) != len(request.evidence_upload_ids):
            raise ServiceError("One or more evidence uploads are invalid or already used.", 422)

        for upload in uploads:
            source_etags[upload.id] = _verify_uploaded_file(upload, storage)

        report = Report(
            company_name=request.company_name,
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
            temporary_keys.append(upload.object_key)
            permanent_key = f"reports/{report.id}/evidence/{uuid.uuid4().hex}"
            storage.promote_object(
                upload.object_key,
                permanent_key,
                upload.content_type,
                source_etags[upload.id],
            )
            promoted_keys.append(permanent_key)
            upload.object_key = permanent_key
            upload.report_id = report.id
            upload.upload_status = "claimed"

        report_repository.add_moderation_log(
            session,
            ModerationLog(
                report_id=report.id,
                moderator="system",
                old_status=None,
                new_status="submitted",
                note="Report submitted for review.",
            ),
        )
        session.commit()
    except Exception:
        session.rollback()
        for object_key in promoted_keys:
            storage.delete_object(object_key)
        raise

    for object_key in temporary_keys:
        storage.delete_object(object_key)

    logger.info("Report %s was submitted with %d evidence files", report.id, len(uploads))
    return {"id": report.id, "message": "Your report has been received for review.", "status": "Submitted"}


def list_reports(session: Session, query: str, page: int, page_size: int) -> dict[str, object]:
    reports, total = report_repository.list_public_reports(session, query, page, page_size)
    return {
        "items": [public_report(report) for report in reports],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_report(session: Session, report_id: str) -> dict[str, object]:
    report = report_repository.get_public_report(session, report_id)
    if report is None or not report.is_public:
        raise ServiceError("Report not found.", 404)
    return public_report(report)


def get_submission_status(session: Session, report_id: str) -> dict[str, object]:
    report = report_repository.get_public_report(session, report_id)
    if report is None:
        raise ServiceError("Report not found.", 404)
    return submission_status(report)
