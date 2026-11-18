"""Create the complete OfferTrap schema."""

from alembic import op
import sqlalchemy as sa


revision = "1"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Alembic's default tracking column is VARCHAR(32). Widen it for PostgreSQL
    # so revision identifiers are not constrained by that internal default.
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column(
            "alembic_version",
            "version_num",
            type_=sa.Text(),
            nullable=False,
        )

    op.create_table(
        "reports",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("company_name", sa.Text(), nullable=False),
        sa.Column("recruiter_contact", sa.Text(), nullable=True),
        sa.Column("job_title", sa.Text(), nullable=True),
        sa.Column("job_url", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("public_summary", sa.Text(), nullable=True),
        sa.Column("payment_requested", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("submitter_name", sa.Text(), nullable=False),
        sa.Column("submitter_email", sa.Text(), nullable=False),
        sa.Column("is_anonymous", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("review_status", sa.Text(), server_default="submitted", nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_public", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_reports_review_status", "reports", ["review_status"])
    op.create_index("ix_reports_created_at", "reports", ["created_at"])

    op.create_table(
        "evidence_files",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("report_id", sa.Text(), nullable=True),
        sa.Column("original_name", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("upload_status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("object_key", name="uq_evidence_files_object_key"),
    )
    op.create_index("ix_evidence_files_report_id", "evidence_files", ["report_id"])
    op.create_index("ix_evidence_files_upload_status", "evidence_files", ["upload_status"])
    op.create_index("ix_evidence_files_expires_at", "evidence_files", ["expires_at"])
    op.create_index("ix_evidence_files_report_status", "evidence_files", ["report_id", "upload_status"])

    op.create_table(
        "moderation_logs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("report_id", sa.Text(), nullable=False),
        sa.Column("moderator", sa.Text(), nullable=False),
        sa.Column("old_status", sa.Text(), nullable=True),
        sa.Column("new_status", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_moderation_logs_report_id", "moderation_logs", ["report_id"])

    op.create_table(
        "reward_ledger",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("report_id", sa.Text(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("moderator", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_reward_ledger_report_id", "reward_ledger", ["report_id"])


def downgrade() -> None:
    op.drop_index("ix_reward_ledger_report_id", table_name="reward_ledger")
    op.drop_table("reward_ledger")
    op.drop_index("ix_moderation_logs_report_id", table_name="moderation_logs")
    op.drop_table("moderation_logs")
    op.drop_index("ix_evidence_files_report_status", table_name="evidence_files")
    op.drop_index("ix_evidence_files_expires_at", table_name="evidence_files")
    op.drop_index("ix_evidence_files_upload_status", table_name="evidence_files")
    op.drop_index("ix_evidence_files_report_id", table_name="evidence_files")
    op.drop_table("evidence_files")
    op.drop_index("ix_reports_created_at", table_name="reports")
    op.drop_index("ix_reports_review_status", table_name="reports")
    op.drop_table("reports")
