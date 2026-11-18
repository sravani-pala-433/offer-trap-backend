from app.core.models import EvidenceFile, Report
from app.services.evidence_service import UPLOAD_CHUNK_SIZE_BYTES, evidence_chunk_count


STATUS_LABELS = {
    "submitted": "Published - unverified",
    "rejected": "Rejected",
}


def public_review_status(status: str) -> str:
    """Normalize historical workflow states to the current two-state model."""
    return "rejected" if status == "rejected" else "submitted"


def status_label(status: str) -> str:
    return STATUS_LABELS[public_review_status(status)]


def public_report(report: Report) -> dict[str, object]:
    publicly_visible = report.is_public and report.review_status != "rejected"
    review_status = public_review_status(report.review_status)
    public_title = (
        f"{report.job_title} recruitment report" if publicly_visible and report.job_title
        else f"{report.category} recruitment report" if publicly_visible
        else f"{report.category} community submission"
    )
    description = report.description.strip()
    summary = None
    if publicly_visible:
        summary = description if len(description) <= 280 else description[:277].rsplit(" ", 1)[0] + "..."

    submitted_by = "Anonymous" if report.is_anonymous else report.submitter_name

    return {
        "id": report.id,
        "company_name": report.company_name,
        "title": public_title,
        "category": report.category,
        "summary": summary,
        "date": report.created_at,
        "status": status_label(review_status),
        "review_status": review_status,
        "is_redacted": not publicly_visible,
        "identifier": report.recruiter_contact if publicly_visible else None,
        "submitted_by": submitted_by,
        "description": None,
        "evidence": [],
        "related_count": 0,
        "payment_requested": report.payment_requested,
        "recruiter_name": report.recruiter_name if publicly_visible else None,
        "job_title": report.job_title if publicly_visible else None,
        "job_url": report.job_url if publicly_visible else None,
    }


def admin_evidence(evidence: EvidenceFile) -> dict[str, object]:
    return {
        "id": evidence.id,
        "name": evidence.original_name,
        "content_type": evidence.content_type,
        "size_bytes": evidence.size_bytes,
        "chunk_size_bytes": UPLOAD_CHUNK_SIZE_BYTES,
        "chunk_count": evidence_chunk_count(evidence.size_bytes),
    }


def admin_report(report: Report) -> dict[str, object]:
    result = public_report(report)
    result.update(
        {
            "description": report.description,
            "submitter_name": report.submitter_name,
            "submitter_email": report.submitter_email,
            "is_anonymous": report.is_anonymous,
            "recruiter_name": report.recruiter_name,
            "recruiter_contact": report.recruiter_contact,
            "review_note": report.review_note,
            "reviewed_at": report.reviewed_at,
            "evidence": [admin_evidence(item) for item in report.evidence_files],
            "reward_points": sum(entry.points for entry in report.reward_entries),
        }
    )
    return result


def submission_status(report: Report) -> dict[str, object]:
    return {
        "id": report.id,
        "company_name": report.company_name,
        "submitted_by": (
            "Anonymous"
            if report.is_anonymous
            else report.submitter_name
        ),
        "status": status_label(report.review_status),
        "review_status": public_review_status(report.review_status),
        "review_note": report.review_note,
        "submitted_at": report.created_at,
        "reviewed_at": report.reviewed_at,
        "is_public": report.is_public and report.review_status != "rejected",
        "reward_points": sum(entry.points for entry in report.reward_entries),
    }
