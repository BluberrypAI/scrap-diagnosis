"""서류 값 후보·검수·효력 해제: document_values, documents.version, fact_records.revoked

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-09 15:00:00

- document_values: 업로드·직접 입력 값은 판정에 쓰지 않는 후보(UNVERIFIED)로 저장하고, 서버가
  검수 완료로 보낸 값만 EVIDENCED로 적용한다(APPLIED). 서류 교체·검수 취소는 REVOKED.
- documents.version: 같은 서류의 파일을 바꾸면 올린다. 기존 행은 1, updated_at은 NULL.
- fact_records.revoked: 서류 효력 해제 표시 행(app/domain/facts.py). 기존 행은 false.
기존 업로드로 이미 EVIDENCED가 된 사실은 그대로 둔다(출처 표기는 버전 없는 문서 id).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("version", sa.Integer(), server_default="1", nullable=False))
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("fact_records", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("revoked", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
    op.create_table(
        "document_values",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("document_id", sa.String(length=32), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=True),
        sa.Column("fact_key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("unit", sa.String(length=30), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reviewer", sa.String(length=200), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["case_id"], ["waste_cases.id"], name=op.f("fk_document_values_case_id_waste_cases")
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_values_document_id_documents"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["diagnosis_sessions.id"],
            name=op.f("fk_document_values_session_id_diagnosis_sessions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_values")),
    )
    with op.batch_alter_table("document_values", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_document_values_case_id"), ["case_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_document_values_document_id"), ["document_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("document_values", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_document_values_document_id"))
        batch_op.drop_index(batch_op.f("ix_document_values_case_id"))
    op.drop_table("document_values")
    with op.batch_alter_table("fact_records", schema=None) as batch_op:
        batch_op.drop_column("revoked")
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("version")
