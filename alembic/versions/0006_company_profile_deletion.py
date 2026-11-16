"""기업 정보 버전 기록, 기업 데이터 삭제 이력: deletion_log

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-09 18:00:00

- diagnosis_sessions.company_profile_version, verdicts.company_profile_version: 서버가 보낸
  기업 정보 버전(없으면 NULL).
- deletion_log: 기업 데이터 삭제 이력(기업 id SHA-256, 테이블별 삭제 건수, 상태, 재시도 횟수).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("diagnosis_sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("company_profile_version", sa.String(64), nullable=True))
    with op.batch_alter_table("verdicts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("company_profile_version", sa.String(64), nullable=True))
    op.create_table(
        "deletion_log",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("company_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deletion_log")),
    )
    with op.batch_alter_table("deletion_log", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_deletion_log_company_hash"), ["company_hash"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("deletion_log", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_deletion_log_company_hash"))
    op.drop_table("deletion_log")
    with op.batch_alter_table("verdicts", schema=None) as batch_op:
        batch_op.drop_column("company_profile_version")
    with op.batch_alter_table("diagnosis_sessions", schema=None) as batch_op:
        batch_op.drop_column("company_profile_version")
