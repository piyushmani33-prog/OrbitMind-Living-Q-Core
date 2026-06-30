"""phase 4c geometry-derived eligibility labels

Allows persisted planning provenance and eligibility rows to distinguish eligibility
derived from authenticated observation-geometry output from eligibility derived from
declared input. No tables or columns are added in this revision.

Revision ID: m8b9c0d1e2f3
Revises: l7a8b9c0d1e2
Create Date: 2026-06-30 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "m8b9c0d1e2f3"
down_revision: str | None = "l7a8b9c0d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OIP_VERIFICATION_OLD = (
    "verification_status IN ('fixture_verified', 'user_declared', "
    "'derived_from_declared', 'unverified', 'unknown')"
)
_OIP_VERIFICATION_NEW = (
    "verification_status IN ('fixture_verified', 'user_declared', "
    "'derived_from_declared', 'geometry_derived', 'unverified', 'unknown')"
)
_OEW_DECLARATION_OLD = (
    "declaration_mode IN ('fixture_backed', 'user_declared', 'derived_from_declared_input')"
)
_OEW_DECLARATION_NEW = (
    "declaration_mode IN ('fixture_backed', 'user_declared', "
    "'derived_from_declared_input', 'derived_from_geometry')"
)


def upgrade() -> None:
    with op.batch_alter_table("observation_input_provenance") as batch_op:
        batch_op.drop_constraint("ck_oip_verification_status", type_="check")
        batch_op.create_check_constraint("ck_oip_verification_status", _OIP_VERIFICATION_NEW)

    with op.batch_alter_table("observation_eligibility_windows") as batch_op:
        batch_op.drop_constraint("ck_oew_declaration_mode", type_="check")
        batch_op.create_check_constraint("ck_oew_declaration_mode", _OEW_DECLARATION_NEW)
        batch_op.drop_constraint("ck_oew_verification_status", type_="check")
        batch_op.create_check_constraint("ck_oew_verification_status", _OIP_VERIFICATION_NEW)


def downgrade() -> None:
    with op.batch_alter_table("observation_eligibility_windows") as batch_op:
        batch_op.drop_constraint("ck_oew_verification_status", type_="check")
        batch_op.create_check_constraint("ck_oew_verification_status", _OIP_VERIFICATION_OLD)
        batch_op.drop_constraint("ck_oew_declaration_mode", type_="check")
        batch_op.create_check_constraint("ck_oew_declaration_mode", _OEW_DECLARATION_OLD)

    with op.batch_alter_table("observation_input_provenance") as batch_op:
        batch_op.drop_constraint("ck_oip_verification_status", type_="check")
        batch_op.create_check_constraint("ck_oip_verification_status", _OIP_VERIFICATION_OLD)
