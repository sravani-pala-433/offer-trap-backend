from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


ReviewStatus = Literal["submitted", "under_review", "needs_information", "approved", "rejected"]
ReviewDecision = Literal["needs_information", "approved", "rejected"]


class PresignFileRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=120)
    size_bytes: int = Field(gt=0)


class PresignRequest(BaseModel):
    files: list[PresignFileRequest] = Field(min_length=1, max_length=5)


class PresignedUpload(BaseModel):
    upload_id: str
    upload_url: str
    method: Literal["PUT"] = "PUT"
    headers: dict[str, str]
    expires_at: datetime


class PresignResponse(BaseModel):
    uploads: list[PresignedUpload]


class ReportCreateRequest(BaseModel):
    contributor_username: str = Field(min_length=2, max_length=120)
    contributor_email: EmailStr
    anonymous_attribution: bool = False
    company_name: str = Field(min_length=2, max_length=200)
    recruiter_contact: str | None = Field(default=None, max_length=10)
    job_title: str | None = Field(default=None, max_length=200)
    job_url: str | None = Field(default=None, max_length=2048)
    category: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=20, max_length=10000)
    payment_requested: bool = False
    evidence_upload_ids: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("contributor_username")
    @classmethod
    def validate_contributor_name(cls, value: str) -> str:
        value = value.strip()
        allowed_punctuation = {" ", ".", "'", "’", "-"}
        contains_letter = False
        for character in value:
            if character.isalpha():
                contains_letter = True
                continue
            if character in allowed_punctuation:
                continue
            raise ValueError("Enter a name using letters, spaces, apostrophes, periods, or hyphens.")
        if not contains_letter or len(value) < 2:
            raise ValueError("Enter a valid name with at least two characters.")
        return value

    @field_validator("company_name", "category", "description")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field is required.")
        return value

    @field_validator("description")
    @classmethod
    def validate_description_length(cls, value: str) -> str:
        if len(value) < 20:
            raise ValueError("Description must contain at least 20 characters.")
        return value

    @field_validator("company_name", "category")
    @classmethod
    def validate_short_required_text(cls, value: str) -> str:
        if len(value) < 2:
            raise ValueError("This field must contain at least two characters.")
        return value

    @field_validator("job_title")
    @classmethod
    def normalize_job_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("contributor_email", mode="before")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("recruiter_contact")
    @classmethod
    def validate_recruiter_mobile(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not value.isascii() or not value.isdigit() or len(value) != 10:
            raise ValueError("Recruiter mobile number must contain exactly 10 digits.")
        return value

    @field_validator("job_url")
    @classmethod
    def validate_job_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        from urllib.parse import urlsplit

        value = value.strip()
        parsed = urlsplit(value)
        try:
            port = parsed.port
        except ValueError as error:
            raise ValueError("Job URL contains an invalid port.") from error
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or port == 0:
            raise ValueError("Job URL must start with http:// or https://.")
        return value

    @field_validator("evidence_upload_ids")
    @classmethod
    def validate_unique_upload_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("An evidence upload can only be attached once.")
        return value


class ReportSubmissionResponse(BaseModel):
    id: str
    message: str
    status: str


class PublicReportResponse(BaseModel):
    id: str
    company_name: str
    title: str
    category: str
    summary: str | None
    date: datetime
    status: str
    review_status: ReviewStatus
    is_redacted: bool
    identifier: str | None
    submitted_by: str | None
    related_count: int = 0
    payment_requested: bool
    job_title: str | None
    job_url: str | None


class ReportListResponse(BaseModel):
    items: list[PublicReportResponse]
    total: int
    page: int
    page_size: int


class SubmissionStatusResponse(BaseModel):
    id: str
    company_name: str
    submitted_by: str | None
    status: str
    review_status: ReviewStatus
    review_note: str | None
    submitted_at: datetime
    reviewed_at: datetime | None
    is_public: bool
    reward_points: int = 0


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=1024)


class AdminLoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: int


class ReportReviewRequest(BaseModel):
    status: ReviewDecision
    review_note: str | None = Field(default=None, max_length=2000)
    public_summary: str | None = Field(default=None, max_length=1200)

    @field_validator("review_note", "public_summary")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class AdminEvidenceResponse(BaseModel):
    id: str
    name: str
    content_type: str
    size_bytes: int


class AdminReportResponse(PublicReportResponse):
    model_config = ConfigDict(from_attributes=True)

    description: str
    submitter_name: str
    submitter_email: EmailStr
    is_anonymous: bool
    recruiter_contact: str | None
    review_note: str | None
    reviewed_at: datetime | None
    evidence: list[AdminEvidenceResponse]
    reward_points: int = 0


class AdminReportListResponse(BaseModel):
    items: list[AdminReportResponse]
