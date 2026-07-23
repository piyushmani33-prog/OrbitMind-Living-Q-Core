"""U8.1A tool gateway decision records."""

import sqlalchemy as sa
from alembic import op

revision = "b8f3a2c9d4e1"
down_revision = "a1f4c7e9b230"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_gateway_decision_records",
        sa.Column("gateway_decision_id", sa.String(128), nullable=False),
        sa.Column("owner_id", sa.String(120), nullable=False),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("proposal_id", sa.String(128), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("tool_id", sa.String(64), nullable=False),
        sa.Column("tool_version", sa.String(32), nullable=False),
        sa.Column("descriptor_checksum", sa.String(64)),
        sa.Column("referenced_admission_id", sa.String(128), nullable=False),
        sa.Column("resolved_admission_id", sa.String(128)),
        sa.Column("admission_record_identity", sa.String(64)),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("primary_reason_code", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(), nullable=False),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("proposal_fingerprint", sa.String(64), nullable=False),
        sa.Column("decision_checksum", sa.String(64), nullable=False),
        sa.Column("record_identity", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("canonical_payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint(
            "gateway_decision_id", "owner_id", name="pk_tool_gateway_records_owner"
        ),
        sa.UniqueConstraint(
            "owner_id", "idempotency_key", name="uq_tool_gateway_records_idempotency"
        ),
        sa.ForeignKeyConstraint(
            ["resolved_admission_id", "owner_id"],
            ["operation_admission_records.admission_id", "operation_admission_records.owner_id"],
            name="fk_tool_gateway_records_resolved_admission_owner",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("length(owner_id) > 0", name="ck_tool_gateway_records_owner"),
        sa.CheckConstraint(
            "schema_version = 'tool-gateway-v0'", name="ck_tool_gateway_records_schema"
        ),
        sa.CheckConstraint("length(record_identity) = 64", name="ck_tool_gateway_records_identity"),
        sa.CheckConstraint(
            "outcome IN ('eligible', 'denied', 'approval_required')",
            name="ck_tool_gateway_records_outcome",
        ),
    )
    op.create_index(
        "ix_tool_gateway_records_owner_created",
        "tool_gateway_decision_records",
        ["owner_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tool_gateway_records_owner_created", table_name="tool_gateway_decision_records"
    )
    op.drop_table("tool_gateway_decision_records")
