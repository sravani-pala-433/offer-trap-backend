"""Add optional recruiter name to reports."""

from alembic import op
import sqlalchemy as sa


revision = "2"
down_revision = "1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("recruiter_name", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("reports", "recruiter_name")
