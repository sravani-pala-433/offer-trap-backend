import logging
from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.settings import Settings, settings
from app.utils.error_helpers import ServiceError


logger = logging.getLogger(__name__)


class B2StorageService:
    """S3-compatible operations for private Backblaze B2 evidence storage."""

    def __init__(self, config: Settings = settings) -> None:
        self.config = config

    @property
    def bucket_name(self) -> str:
        self._ensure_configured()
        return self.config.b2_bucket_name or ""

    def _ensure_configured(self) -> None:
        if not self.config.b2_is_configured:
            raise ServiceError(
                "Evidence storage is not configured. Set the Backblaze B2 environment variables.",
                status_code=503,
            )

    @property
    def client(self) -> Any:
        self._ensure_configured()
        return _s3_client(
            self.config.resolved_b2_endpoint_url or "",
            self.config.b2_region or "",
            self.config.b2_application_key_id.get_secret_value(),  # type: ignore[union-attr]
            self.config.b2_application_key.get_secret_value(),  # type: ignore[union-attr]
        )

    def create_upload_url(self, object_key: str, content_type: str) -> str:
        try:
            return self.client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self.bucket_name,
                    "Key": object_key,
                    "ContentType": content_type,
                },
                ExpiresIn=self.config.b2_presigned_url_ttl_seconds,
            )
        except (BotoCoreError, ClientError):
            logger.exception("Could not create a Backblaze B2 upload URL")
            raise ServiceError("Could not prepare secure evidence upload.", status_code=503) from None

    def inspect_object(self, object_key: str) -> dict[str, Any] | None:
        try:
            return self.client.head_object(Bucket=self.bucket_name, Key=object_key)
        except ClientError as error:
            if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                return None
            logger.exception("Could not inspect a Backblaze B2 evidence object")
            raise ServiceError("Could not verify uploaded evidence.", status_code=503) from None
        except BotoCoreError:
            logger.exception("Could not inspect a Backblaze B2 evidence object")
            raise ServiceError("Could not verify uploaded evidence.", status_code=503) from None

    def read_object_prefix(self, object_key: str, length: int = 65_536) -> bytes:
        try:
            response = self.client.get_object(
                Bucket=self.bucket_name,
                Key=object_key,
                Range=f"bytes=0-{length - 1}",
            )
            body = response["Body"]
            try:
                return body.read(length)
            finally:
                body.close()
        except (BotoCoreError, ClientError):
            logger.exception("Could not inspect the uploaded evidence content")
            raise ServiceError("Could not inspect uploaded evidence.", status_code=503) from None

    def promote_object(
        self,
        source_key: str,
        destination_key: str,
        content_type: str,
        source_etag: str,
    ) -> None:
        try:
            self.client.copy_object(
                Bucket=self.bucket_name,
                CopySource={"Bucket": self.bucket_name, "Key": source_key},
                CopySourceIfMatch=source_etag,
                Key=destination_key,
                ContentType=content_type,
                MetadataDirective="REPLACE",
            )
        except ClientError as error:
            if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 412:
                raise ServiceError("An evidence file changed during submission. Please upload it again.", 409) from None
            logger.exception("Could not move submitted evidence into private report storage")
            raise ServiceError("Could not finalize evidence upload.", status_code=503) from None
        except BotoCoreError:
            logger.exception("Could not move submitted evidence into private report storage")
            raise ServiceError("Could not finalize evidence upload.", status_code=503) from None

    def delete_object(self, object_key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=object_key)
        except (BotoCoreError, ClientError):
            logger.exception("Could not delete temporary Backblaze B2 evidence object")

    def open_object(self, object_key: str) -> dict[str, Any]:
        try:
            return self.client.get_object(Bucket=self.bucket_name, Key=object_key)
        except ClientError as error:
            if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                raise ServiceError("Evidence file is unavailable.", status_code=404) from None
            logger.exception("Could not read private Backblaze B2 evidence object")
            raise ServiceError("Could not retrieve evidence file.", status_code=503) from None
        except BotoCoreError:
            logger.exception("Could not read private Backblaze B2 evidence object")
            raise ServiceError("Could not retrieve evidence file.", status_code=503) from None


@lru_cache(maxsize=1)
def get_storage_service() -> B2StorageService:
    return B2StorageService()


@lru_cache(maxsize=4)
def _s3_client(
    endpoint_url: str,
    region: str,
    access_key_id: str,
    secret_access_key: str,
) -> Any:
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name=region,
        config=Config(signature_version="s3v4"),
    )
