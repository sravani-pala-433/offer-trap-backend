from app.core.models import EvidenceFile, Report


STATUS_LABELS = {
    "submitted": "Submitted",
    "under_review": "Under Review",
    "needs_information": "Needs Information",
    "approved": "Approved",
    "rejected": "Rejected",
}


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, "Under Review")


def public_report(report: Report) -> dict[str, object]:
    approved = report.review_status == "approved"
    public_title = (
        f"{report.job_title} recruitment report" if approved and report.job_title
        else f"{report.category} recruitment report" if approved
        else f"{report.category} community submission"
    )
    if approved:
        summary = report.public_summary or (
            f"A community report about {report.company_name} was reviewed and approved."
        )
    else:
        summary = None

    submitted_by = (
        "Anonymous"
        if report.is_anonymous
        else report.submitter_name if approved
        else None
    )

    return {
        "id": report.id,
        "company_name": report.company_name,
        "title": public_title,
        "category": report.category,
        "summary": summary,
        "date": report.created_at,
        "status": status_label(report.review_status),
        "review_status": report.review_status,
        "is_redacted": not approved,
        "identifier": report.recruiter_contact if approved else None,
        "submitted_by": submitted_by,
        "related_count": 0,
        "payment_requested": report.payment_requested,
        "job_title": report.job_title if approved else None,
        "job_url": report.job_url if approved else None,
    }


def admin_evidence(evidence: EvidenceFile) -> dict[str, object]:
    return {
        "id": evidence.id,
        "name": evidence.original_name,
        "content_type": evidence.content_type,
        "size_bytes": evidence.size_bytes,
    }


def admin_report(report: Report) -> dict[str, object]:
    result = public_report(report)
    result.update(
        {
            "description": report.description,
            "submitter_name": report.submitter_name,
            "submitter_email": report.submitter_email,
            "is_anonymous": report.is_anonymous,
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
            else report.submitter_name if report.review_status == "approved"
            else None
        ),
        "status": status_label(report.review_status),
        "review_status": report.review_status,
        "review_note": report.review_note,
        "submitted_at": report.created_at,
        "reviewed_at": report.reviewed_at,
        "is_public": report.is_public,
        "reward_points": sum(entry.points for entry in report.reward_entries),
    }
