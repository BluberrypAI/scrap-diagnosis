"""사실 철회: fact_records.retracted

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-08 23:00:00

사용자가 보드에서 "모름으로 되돌리기"를 누르면 status UNKNOWN, retracted true인 행을 남긴다
(docs/ui/ui-contract.md 4절). 기존 행은 false로 채운다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("fact_records", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("retracted", sa.Boolean(), server_default=sa.false(), nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("fact_records", schema=None) as batch_op:
        batch_op.drop_column("retracted")
