"""인계 객체·시각: 세션 시작/마지막 활동, 판정 result_type·outcome·handoff·reopen

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-08 21:00:00

기존 행은 다음 값으로 채운다.
- diagnosis_sessions.started_at ← created_at, last_activity_at ← updated_at
- verdicts.result_type ← code가 있으면 WASTE_CODE, 없으면 NO_CODE
- verdicts.reopened_at ← superseded_at(0001까지는 reopen만 superseded_at을 채웠다)
- verdicts.handoff는 비워 둔다(확정 당시 값으로 다시 만들 수 없으므로)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("diagnosis_sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True)
        )
    op.execute("UPDATE diagnosis_sessions SET started_at = created_at WHERE started_at IS NULL")
    op.execute(
        "UPDATE diagnosis_sessions SET last_activity_at = updated_at WHERE last_activity_at IS NULL"
    )
    with op.batch_alter_table("diagnosis_sessions", schema=None) as batch_op:
        batch_op.alter_column(
            "started_at", existing_type=sa.DateTime(timezone=True), nullable=False
        )
        batch_op.alter_column(
            "last_activity_at", existing_type=sa.DateTime(timezone=True), nullable=False
        )

    with op.batch_alter_table("verdicts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("result_type", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("outcome", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("handoff", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("reopened_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("reopen_reason", sa.Text(), nullable=True))
    op.execute(
        "UPDATE verdicts SET result_type = CASE WHEN code IS NULL THEN 'NO_CODE' "
        "ELSE 'WASTE_CODE' END WHERE result_type IS NULL"
    )
    op.execute("UPDATE verdicts SET reopened_at = superseded_at WHERE reopened_at IS NULL")
    with op.batch_alter_table("verdicts", schema=None) as batch_op:
        batch_op.alter_column("result_type", existing_type=sa.String(length=20), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("verdicts", schema=None) as batch_op:
        batch_op.drop_column("reopen_reason")
        batch_op.drop_column("reopened_at")
        batch_op.drop_column("handoff")
        batch_op.drop_column("outcome")
        batch_op.drop_column("result_type")
    with op.batch_alter_table("diagnosis_sessions", schema=None) as batch_op:
        batch_op.drop_column("last_activity_at")
        batch_op.drop_column("started_at")
