"""기업 외부 ID: companies.external_id

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-09 10:00:00

scrap-server가 보내는 기업 ID(`X-Company-Id`)를 저장한다. 처음 보는 ID는 내부 기업 레코드로
자동 생성한다(docs/api/server-engine-contract.md). 개발용으로 만든 기업은 NULL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("companies", schema=None) as batch_op:
        batch_op.add_column(sa.Column("external_id", sa.String(length=128), nullable=True))
        batch_op.create_unique_constraint(batch_op.f("uq_companies_external_id"), ["external_id"])


def downgrade() -> None:
    with op.batch_alter_table("companies", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("uq_companies_external_id"), type_="unique")
        batch_op.drop_column("external_id")
