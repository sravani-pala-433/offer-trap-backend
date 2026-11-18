"""Private Neon Object Storage access through its S3-compatible API."""

from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.settings import settings


class EvidenceStorageError(Exception):
    """A safe-to-report storage error without credentials or signed URLs."""


@lru_cache(maxsize=1)
def _client():
    if not settings.neon_storage_is_configured:
        raise EvidenceStorageError(
            "Neon Object Storage is not configured. Set the AWS_* storage values and NEON_STORAGE_BUCKET."
        )
    return boto3.client(
        "s3",
        endpoint_url=settings.aws_endpoint_url_s3.rstrip("/"),
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id.get_secret_value(),
        aws_secret_access_key=settings.aws_secret_access_key.get_secret_value(),
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def _bucket() -> str:
    bucket = settings.neon_storage_bucket
    if not bucket or not bucket.strip():
        raise EvidenceStorageError("NEON_STORAGE_BUCKET is not configured.")
    return bucket.strip()


def chunk_object_key(object_key: str, chunk_index: int) -> str:
    return f"{object_key.rstrip('/')}/chunks/{chunk_index:08d}"


def ensure_configured() -> None:
    _client()
    _bucket()


def _raise_storage_error(action: str, error: Exception) -> EvidenceStorageError:
    if isinstance(error, EvidenceStorageError):
        return error
    return EvidenceStorageError(f"Neon Object Storage could not {action} the evidence image.")


def put_chunk(object_key: str, chunk_index: int, data: bytes) -> None:
    try:
        _client().put_object(
            Bucket=_bucket(),
            Key=chunk_object_key(object_key, chunk_index),
            Body=data,
            ContentType="application/octet-stream",
        )
    except (BotoCoreError, ClientError, EvidenceStorageError) as error:
        raise _raise_storage_error("store", error) from None


def get_chunk(object_key: str, chunk_index: int) -> bytes:
    try:
        response = _client().get_object(
            Bucket=_bucket(), Key=chunk_object_key(object_key, chunk_index)
        )
        body = response["Body"]
        try:
            return body.read()
        finally:
            body.close()
    except (BotoCoreError, ClientError, EvidenceStorageError) as error:
        raise _raise_storage_error("read", error) from None


def head_chunk_size(object_key: str, chunk_index: int) -> int | None:
    try:
        response = _client().head_object(
            Bucket=_bucket(), Key=chunk_object_key(object_key, chunk_index)
        )
        return int(response["ContentLength"])
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code", ""))
        status_code = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {"404", "NoSuchKey", "NotFound", "NoSuchObject"} or status_code == 404:
            return None
        raise _raise_storage_error("check", error) from None
    except (BotoCoreError, EvidenceStorageError) as error:
        raise _raise_storage_error("check", error) from None


def delete_chunks(object_key: str, chunk_count: int) -> None:
    if chunk_count < 1:
        return
    try:
        client = _client()
        bucket = _bucket()
        for index in range(chunk_count):
            client.delete_object(
                Bucket=bucket, Key=chunk_object_key(object_key, index)
            )
    except (BotoCoreError, ClientError, EvidenceStorageError) as error:
        raise _raise_storage_error("delete", error) from None
