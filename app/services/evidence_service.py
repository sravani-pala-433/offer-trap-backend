"""Upload and stream evidence-image chunks through Neon Object Storage."""

import logging
import math
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.models import EvidenceFile, Report, utc_now
from app.core.schemas import EvidenceUploadRequest
from app.core.settings import settings
from app.repositories import admin_repository, report_repository
from app.services import storage_service
from app.services.storage_service import EvidenceStorageError
from app.utils.error_helpers import ServiceError


logger = logging.getLogger(__name__)

CONTENT_TYPES_BY_EXTENSION = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
PUBLIC_IMAGE_CONTENT_TYPES = frozenset(CONTENT_TYPES_BY_EXTENSION.values())
SAFE_FILENAME_PATTERN = re.compile(r"[^\w .()\-]", re.UNICODE)

# Vercel Functions reject request bodies larger than 4.5 MB. Each small request
# is streamed by the API to a separate object in Neon Object Storage.
UPLOAD_CHUNK_SIZE_BYTES = 4 * 1024 * 1024
OBJECT_KEY_PREFIX = "offertrap-evidence/"


def _utc_datetime(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _storage_error(error: EvidenceStorageError) -> ServiceError:
    logger.error("evidence_storage_failed reason=%s", error)
    return ServiceError(str(error), 503)


def _normalize_filename(filename: str) -> tuple[str, str]:
    filename = filename.replace("\\", "/").split("/")[-1].strip()
    extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    expected_type = CONTENT_TYPES_BY_EXTENSION.get(extension)
    if not expected_type:
        raise ServiceError("Only JPEG, PNG, and WEBP evidence images are supported.", 422)

    safe_name = SAFE_FILENAME_PATTERN.sub("_", filename).strip(" .")
    if not safe_name:
        safe_name = f"evidence{extension}"
    return safe_name, expected_type


def _expected_chunk_count(size_bytes: int) -> int:
    return math.ceil(size_bytes / UPLOAD_CHUNK_SIZE_BYTES)


def evidence_chunk_count(size_bytes: int) -> int:
    return _expected_chunk_count(size_bytes)


def _expected_chunk_size(size_bytes: int, chunk_index: int) -> int:
    remaining = size_bytes - chunk_index * UPLOAD_CHUNK_SIZE_BYTES
    return min(UPLOAD_CHUNK_SIZE_BYTES, remaining)


def _verify_chunk_layout(upload: EvidenceFile) -> None:
    object_key = upload.object_key
    if not object_key or not object_key.startswith(OBJECT_KEY_PREFIX):
        raise ServiceError("Evidence is not stored in Neon Object Storage.", 422)
    expected_count = _expected_chunk_count(upload.size_bytes)

    def verify_chunk_size(chunk_index: int, actual_size: int | None) -> None:
        if actual_size != _expected_chunk_size(upload.size_bytes, chunk_index):
            raise ServiceError(
                "Evidence upload is incomplete. Please retry the upload.", 422
            )

    try:
        if expected_count == 1:
            verify_chunk_size(
                0, storage_service.head_chunk_size(object_key, 0)
            )
        else:
            # Check a few independent object parts at once. Bounded batches keep
            # large uploads from creating an unbounded number of storage calls.
            with ThreadPoolExecutor(max_workers=4) as executor:
                for batch_start in range(0, expected_count, 4):
                    chunk_indexes = range(
                        batch_start, min(batch_start + 4, expected_count)
                    )
                    actual_sizes = executor.map(
                        lambda index: storage_service.head_chunk_size(
                            object_key, index
                        ),
                        chunk_indexes,
                    )
                    for chunk_index, actual_size in zip(chunk_indexes, actual_sizes):
                        verify_chunk_size(chunk_index, actual_size)
    except EvidenceStorageError as error:
        raise _storage_error(error) from None


def _verify_image_signature(upload: EvidenceFile, first_chunk: bytes) -> None:
    extension = upload.original_name.rsplit(".", 1)[-1].lower()
    valid_signature = {
        "png": first_chunk.startswith(b"\x89PNG\r\n\x1a\n"),
        "jpg": first_chunk.startswith(b"\xff\xd8\xff"),
        "jpeg": first_chunk.startswith(b"\xff\xd8\xff"),
        "webp": len(first_chunk) >= 12 and first_chunk[:4] == b"RIFF" and first_chunk[8:12] == b"WEBP",
    }.get(extension, False)
    if not valid_signature:
        raise ServiceError("The evidence content does not match its file extension.", 422)


def initiate_upload(session: Session, request: EvidenceUploadRequest) -> dict[str, Any]:
    try:
        storage_service.ensure_configured()
    except EvidenceStorageError as error:
        raise _storage_error(error) from None

    filename, expected_type = _normalize_filename(request.filename)
    declared_type = request.content_type.split(";", maxsplit=1)[0].strip().lower()
    if declared_type not in {expected_type, "application/octet-stream"}:
        raise ServiceError("The selected file extension does not match its file type.", 422)

    upload_id = str(uuid.uuid4())
    record = EvidenceFile(
        id=upload_id,
        report_id=None,
        original_name=filename,
        object_key=f"{OBJECT_KEY_PREFIX}{upload_id}",
        content_type=expected_type,
        size_bytes=request.size_bytes,
        upload_status="uploading",
        expires_at=utc_now() + timedelta(minutes=settings.evidence_upload_ttl_minutes),
    )
    try:
        report_repository.add_evidence_upload(session, record)
        session.commit()
    except Exception:
        session.rollback()
        raise

    logger.info("evidence_upload_started upload_id=%s size_bytes=%d", upload_id, request.size_bytes)
    return {
        "upload_id": upload_id,
        "chunk_size_bytes": UPLOAD_CHUNK_SIZE_BYTES,
        "chunk_count": _expected_chunk_count(request.size_bytes),
    }


def store_upload_chunk(
    session: Session, upload_id: str, chunk_index: int, data: bytes
) -> None:
    try:
        upload = report_repository.get_evidence_upload_for_update(session, upload_id)
        if upload is None:
            raise ServiceError("Evidence upload not found.", 404)
        if _utc_datetime(upload.expires_at) <= utc_now():
            raise ServiceError("This evidence upload has expired. Please start again.", 410)
        if upload.upload_status != "uploading":
            raise ServiceError("This evidence upload is not accepting more chunks.", 409)

        chunk_count = _expected_chunk_count(upload.size_bytes)
        if chunk_index < 0 or chunk_index >= chunk_count:
            raise ServiceError("Evidence chunk index is invalid.", 422)
        expected_size = _expected_chunk_size(upload.size_bytes, chunk_index)
        if len(data) != expected_size:
            raise ServiceError("Evidence chunk size does not match the upload manifest.", 422)
        if not upload.object_key:
            raise ServiceError("Evidence upload is missing its object key.", 500)
        if chunk_index == 0:
            # Validate the image using bytes already received from the client;
            # downloading the stored first 4 MiB chunk later is unnecessary.
            _verify_image_signature(upload, data)

        # The browser sends bytes only to this API. This backend call writes the
        # chunk directly to Neon Object Storage, never to a Postgres BYTEA row.
        storage_service.put_chunk(upload.object_key, chunk_index, data)
        session.commit()
    except EvidenceStorageError as error:
        session.rollback()
        raise _storage_error(error) from None
    except Exception:
        session.rollback()
        raise


def complete_upload(session: Session, upload_id: str) -> dict[str, str]:
    try:
        upload = report_repository.get_evidence_upload_for_update(session, upload_id)
        if upload is None:
            raise ServiceError("Evidence upload not found.", 404)
        if _utc_datetime(upload.expires_at) <= utc_now():
            raise ServiceError("This evidence upload has expired. Please start again.", 410)
        if upload.upload_status not in {"uploading", "pending"}:
            raise ServiceError("This evidence upload has already been used.", 409)

        _verify_chunk_layout(upload)
        upload.upload_status = "pending"
        session.commit()
    except Exception:
        session.rollback()
        raise

    logger.info("evidence_upload_completed upload_id=%s", upload_id)
    return {"upload_id": upload_id, "status": "ready"}


def verify_ready_upload(upload: EvidenceFile) -> None:
    if upload.upload_status != "pending":
        raise ServiceError("One or more evidence uploads are not ready to submit.", 422)
    if _utc_datetime(upload.expires_at) <= utc_now():
        raise ServiceError("An evidence upload has expired. Please upload the file again.", 422)
    # The first chunk was signature-checked on receipt and the complete
    # endpoint checked every stored chunk. Pending uploads cannot accept more
    # writes, so repeat storage reads here would only add latency.
    if not upload.object_key or not upload.object_key.startswith(OBJECT_KEY_PREFIX):
        raise ServiceError("Evidence is not stored in Neon Object Storage.", 422)


def evidence_chunks_are_complete(session: Session, upload: EvidenceFile) -> bool:
    if not upload.object_key or not upload.object_key.startswith(OBJECT_KEY_PREFIX):
        return False
    try:
        _verify_chunk_layout(upload)
        return True
    except ServiceError as error:
        if error.status_code == 422:
            return False
        raise


def get_public_evidence(
    session: Session, report_id: str, evidence_id: str, chunk_index: int
) -> tuple[dict[str, Any], bytes]:
    report = report_repository.get_public_report(session, report_id)
    if report is None or not report.is_public or report.review_status == "rejected":
        raise ServiceError("Evidence file not found.", 404)
    evidence = report_repository.get_public_evidence(session, report_id, evidence_id)
    if (
        evidence is None
        or evidence.content_type not in PUBLIC_IMAGE_CONTENT_TYPES
        or not evidence.object_key
        or not evidence.object_key.startswith(OBJECT_KEY_PREFIX)
    ):
        raise ServiceError("Evidence file not found.", 404)
    chunk_count = _expected_chunk_count(evidence.size_bytes)
    if chunk_index < 0 or chunk_index >= chunk_count:
        raise ServiceError("Evidence chunk not found.", 404)
    try:
        chunk = storage_service.get_chunk(evidence.object_key, chunk_index)
    except EvidenceStorageError as error:
        raise _storage_error(error) from None
    return {
        "name": evidence.original_name,
        "content_type": evidence.content_type,
        "size_bytes": evidence.size_bytes,
        "chunk_count": chunk_count,
    }, chunk


def get_admin_evidence(
    session: Session, evidence_id: str, chunk_index: int
) -> tuple[dict[str, Any], bytes]:
    evidence = admin_repository.get_evidence(session, evidence_id)
    if (
        evidence is None
        or not evidence.object_key
        or not evidence.object_key.startswith(OBJECT_KEY_PREFIX)
    ):
        raise ServiceError("Evidence file not found.", 404)
    chunk_count = _expected_chunk_count(evidence.size_bytes)
    if chunk_index < 0 or chunk_index >= chunk_count:
        raise ServiceError("Evidence chunk not found.", 404)
    try:
        chunk = storage_service.get_chunk(evidence.object_key, chunk_index)
    except EvidenceStorageError as error:
        raise _storage_error(error) from None
    return {
        "name": evidence.original_name,
        "content_type": evidence.content_type,
        "size_bytes": evidence.size_bytes,
        "chunk_count": chunk_count,
    }, chunk


def delete_report_evidence(report: Report) -> int:
    """Delete stored image chunks for a report before its database rows are removed."""
    deleted_files = 0
    for evidence in report.evidence_files:
        if not evidence.object_key or not evidence.object_key.startswith(OBJECT_KEY_PREFIX):
            continue
        try:
            storage_service.delete_chunks(
                evidence.object_key, _expected_chunk_count(evidence.size_bytes)
            )
        except EvidenceStorageError as error:
            raise _storage_error(error) from None
        deleted_files += 1
    return deleted_files


def cleanup_expired_uploads(session: Session) -> int:
    try:
        expired = report_repository.get_expired_unclaimed_uploads(session, utc_now())
        for evidence in expired:
            if (
                evidence.object_key
                and evidence.object_key.startswith(OBJECT_KEY_PREFIX)
            ):
                storage_service.delete_chunks(
                    evidence.object_key, _expected_chunk_count(evidence.size_bytes)
                )
        count = report_repository.delete_evidence_uploads(
            session, [evidence.id for evidence in expired]
        )
        session.commit()
        logger.info("expired_evidence_uploads_deleted count=%d", count)
        return count
    except EvidenceStorageError as error:
        session.rollback()
        raise _storage_error(error) from None
    except Exception:
        session.rollback()
        raise
