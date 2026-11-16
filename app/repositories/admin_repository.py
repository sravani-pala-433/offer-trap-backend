from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.models import EvidenceFile, ModerationLog, Report, RewardLedger


def list_reports(
    session: Session, status_filter: str | None = None, query: str = ""
) -> list[Report]:
    statement = select(Report).options(selectinload(Report.evidence_files), selectinload(Report.reward_entries))

    if status_filter:
        statement = statement.where(Report.review_status == status_filter)
    if query:
        pattern = f"%{query}%"
        statement = statement.where(
            or_(
                Report.id.ilike(pattern),
                Report.company_name.ilike(pattern),
                Report.job_title.ilike(pattern),
                Report.submitter_name.ilike(pattern),
                Report.submitter_email.ilike(pattern),
                Report.recruiter_contact.ilike(pattern),
                Report.description.ilike(pattern),
            )
        )

    statement = statement.order_by(Report.created_at.desc())
    return list(session.scalars(statement).unique().all())


def get_report(session: Session, report_id: str, *, lock: bool = False) -> Report | None:
    statement = (
        select(Report)
        .options(selectinload(Report.evidence_files), selectinload(Report.reward_entries))
        .where(Report.id == report_id)
    )
    if lock:
        statement = statement.with_for_update()
    return session.scalars(statement).unique().first()


def add_moderation_log(session: Session, entry: ModerationLog) -> None:
    session.add(entry)


def get_evidence(session: Session, evidence_id: str) -> EvidenceFile | None:
    statement = select(EvidenceFile).where(
        EvidenceFile.id == evidence_id,
        EvidenceFile.upload_status == "claimed",
        EvidenceFile.report_id.is_not(None),
    )
    return session.scalars(statement).first()


def add_reward_entry(session: Session, entry: RewardLedger) -> None:
    session.add(entry)
