from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables or .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "OfferTrap API"
    database_url: str
    secret_key: SecretStr | None = None
    access_token_expire_minutes: int = Field(default=120, ge=5, le=1440)

    admin_username: str | None = None
    admin_password: SecretStr | None = None

    evidence_upload_ttl_minutes: int = Field(default=60, ge=15, le=1440)

    # Neon Object Storage exposes an S3-compatible endpoint. Keep credentials
    # optional so non-upload API routes can start even before storage is set up.
    aws_endpoint_url_s3: str | None = None
    aws_region: str | None = None
    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None
    neon_storage_bucket: str | None = None

    frontend_origins: str = "http://localhost:5173,https://offer-trap.vercel.app"
    log_level: str = "INFO"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]

    @property
    def neon_storage_is_configured(self) -> bool:
        return bool(
            self.aws_endpoint_url_s3
            and self.aws_endpoint_url_s3.strip()
            and self.aws_region
            and self.aws_region.strip()
            and self.aws_access_key_id
            and self.aws_access_key_id.get_secret_value().strip()
            and self.aws_secret_access_key
            and self.aws_secret_access_key.get_secret_value().strip()
            and self.neon_storage_bucket
            and self.neon_storage_bucket.strip()
        )

@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
