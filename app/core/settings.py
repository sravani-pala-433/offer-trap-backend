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

    b2_region: str | None = None
    b2_endpoint_url: str | None = None
    b2_application_key_id: SecretStr | None = None
    b2_application_key: SecretStr | None = None
    b2_bucket_name: str | None = None
    b2_presigned_url_ttl_seconds: int = Field(default=600, ge=60, le=3600)

    frontend_origins: str = "http://localhost:5173", "https://offer-trap.vercel.app/"
    reward_points_per_approved_report: int = Field(default=100, ge=0)
    log_level: str = "INFO"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]

    @property
    def resolved_b2_endpoint_url(self) -> str | None:
        if self.b2_endpoint_url:
            return self.b2_endpoint_url.rstrip("/")
        if self.b2_region and self.b2_region.strip():
            return f"https://s3.{self.b2_region.strip()}.backblazeb2.com"
        return None

    @property
    def b2_is_configured(self) -> bool:
        return bool(
            self.resolved_b2_endpoint_url
            and self.b2_region
            and self.b2_region.strip()
            and self.b2_application_key_id
            and self.b2_application_key_id.get_secret_value().strip()
            and self.b2_application_key
            and self.b2_application_key.get_secret_value().strip()
            and self.b2_bucket_name
            and self.b2_bucket_name.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
