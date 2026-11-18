from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.models import EvidenceFile, ModerationLog, Report


def add_evidence_upload(session: Session, upload: EvidenceFile) -> None:
    session.add(upload)
    session.flush()


def get_evidence_upload_for_update(session: Session, upload_id: str) -> EvidenceFile | None:
    statement = select(EvidenceFile).where(EvidenceFile.id == upload_id).with_for_update()
    return session.scalars(statement).first()


def get_expired_unclaimed_uploads(session: Session, now) -> list[EvidenceFile]:
    statement = (
        select(EvidenceFile)
        .where(
            EvidenceFile.report_id.is_(None),
            EvidenceFile.upload_status.in_(("uploading", "pending")),
            EvidenceFile.expires_at <= now,
        )
        .with_for_update()
    )
    return list(session.scalars(statement).all())


def delete_evidence_uploads(session: Session, evidence_ids: list[str]) -> int:
    if not evidence_ids:
        return 0
    result = session.execute(
        delete(EvidenceFile).where(EvidenceFile.id.in_(evidence_ids))
    )
    return int(result.rowcount or 0)


def add_pending_uploads(session: Session, uploads: list[EvidenceFile]) -> None:
    session.add_all(uploads)
    session.flush()


def get_pending_uploads_for_update(session: Session, upload_ids: list[str]) -> list[EvidenceFile]:
    if not upload_ids:
        return []
    statement = (
        select(EvidenceFile)
        .where(EvidenceFile.id.in_(upload_ids))
        .where(EvidenceFile.upload_status == "pending")
        .with_for_update()
    )
    return list(session.scalars(statement).all())


def add_report(session: Session, report: Report) -> None:
    session.add(report)
    session.flush()


def add_moderation_log(session: Session, entry: ModerationLog) -> None:
    session.add(entry)


def get_public_report(session: Session, report_id: str) -> Report | None:
    return session.get(Report, report_id)


def get_public_evidence(
    session: Session, report_id: str, evidence_id: str
) -> EvidenceFile | None:
    statement = select(EvidenceFile).where(
        EvidenceFile.id == evidence_id,
        EvidenceFile.report_id == report_id,
        EvidenceFile.upload_status == "claimed",
    )
    return session.scalars(statement).first()


def list_public_reports(
    session: Session, query: str, page: int, page_size: int
) -> tuple[list[Report], int]:
    conditions = []
    if query:
        pattern = f"%{query}%"
        conditions.append(
            or_(
                Report.id.ilike(pattern),
                Report.company_name.ilike(pattern),
                Report.category.ilike(pattern),
                Report.job_title.ilike(pattern),
                Report.recruiter_name.ilike(pattern),
                Report.review_status.ilike(pattern),
            )
        )

    statement = select(Report).where(Report.is_public.is_(True))
    count_statement = select(func.count(Report.id)).where(Report.is_public.is_(True))
    if conditions:
        statement = statement.where(*conditions)
        count_statement = count_statement.where(*conditions)

    statement = statement.order_by(Report.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    reports = list(session.scalars(statement).all())
    total = session.scalar(count_statement) or 0
    return reports, total
