"""Contract-boundary coverage for Operation Admission v0 (strict, fail-closed)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError

from orbitmind.admission.contracts import (
    OPERATION_ADMISSION_POLICY_VERSION,
    AdmissionContractError,
    AdmissionEvaluationContext,
    AdmissionOperationKind,
    AdmissionRiskClass,
    AdmissionSideEffectClass,
    AuthorityFinding,
    OperationProposal,
    ProposalActorType,
    ProposalScope,
    decision_checksum_source,
    fingerprint_source,
    parse_admission_json,
)

T0 = datetime(2026, 7, 21, tzinfo=UTC)
OWNER = "owner-piyush-01"
ACTOR = "agent-dev-0001"
SCOPE = ProposalScope(resource_type="repository", resource_id="orbitmind-main")


def _proposal(**overrides: Any) -> OperationProposal:
    values: dict[str, Any] = {
        "proposal_id": "prop-00000001",
        "owner_id": OWNER,
        "actor_id": ACTOR,
        "actor_type": ProposalActorType.AGENT,
        "operation_kind": AdmissionOperationKind.READ_REPOSITORY.value,
        "requested_capability": "repository_read",
        "requested_scope": SCOPE,
        "side_effect_class": AdmissionSideEffectClass.LOCAL_READ,
        "risk_class": AdmissionRiskClass.LOW,
        "purpose": "Bounded read for review evidence.",
        "requested_at": T0,
        "idempotency_key": "adm-key-0001",
    }
    values.update(overrides)
    return OperationProposal(**values)


def _context(**overrides: Any) -> AdmissionEvaluationContext:
    values: dict[str, Any] = {
        "authoritative_owner_id": OWNER,
        "authoritative_actor_id": ACTOR,
        "evaluated_at": T0,
    }
    values.update(overrides)
    return AdmissionEvaluationContext(**values)


def test_policy_version_is_module_owned_and_fixed() -> None:
    assert OPERATION_ADMISSION_POLICY_VERSION == "operation-admission-v0"
    assert _context().policy_version == OPERATION_ADMISSION_POLICY_VERSION
    # A proposal has no policy_version field at all — it cannot supply one.
    assert "policy_version" not in OperationProposal.model_fields
    # The context rejects any other value (fails closed before evaluation).
    with pytest.raises(PydanticValidationError):
        _context(policy_version="operation-admission-v1")


def test_proposal_is_frozen_and_closed() -> None:
    with pytest.raises(PydanticValidationError):
        _proposal(extra_field="x")  # extra="forbid"
    proposal = _proposal()
    with pytest.raises(PydanticValidationError):
        proposal.purpose = "changed"  # type: ignore[misc]  # frozen


@pytest.mark.parametrize(
    "override",
    [
        {"owner_id": "BAD OWNER"},
        {"proposal_id": "short"},
        {"idempotency_key": ""},
        {"idempotency_key": " leading-space"},
        {"purpose": "path/like value"},
        {"purpose": "url like ://x"},
        {"requested_capability": "Bad-Capability"},
        {"operation_kind": "Bad-Kind"},
        {"requested_at": datetime(2026, 7, 21)},  # naive
    ],
)
def test_malformed_proposal_is_rejected_at_the_contract_boundary(override: dict[str, Any]) -> None:
    with pytest.raises(PydanticValidationError):
        _proposal(**override)


def test_proposal_has_no_place_for_secrets_or_payloads() -> None:
    # The schema simply has no command/secret/token/argument field.
    for forbidden in ("command", "secret", "token", "arguments", "payload", "prompt", "env"):
        assert forbidden not in OperationProposal.model_fields


def test_fingerprint_excludes_idempotency_key_but_binds_content_and_identity() -> None:
    base = _proposal(idempotency_key="key-a")
    same_content_other_key = _proposal(idempotency_key="key-b")
    context = _context()
    assert fingerprint_source(base, context) == fingerprint_source(same_content_other_key, context)

    other_content = _proposal(purpose="A different bounded purpose.")
    assert fingerprint_source(base, context) != fingerprint_source(other_content, context)

    other_owner_context = _context(authoritative_owner_id="owner-second-02")
    # owner claim mismatch aside, the fingerprint binds the trusted identity.
    assert fingerprint_source(_proposal(owner_id="owner-second-02"), other_owner_context) != (
        fingerprint_source(base, context)
    )


def test_decision_checksum_source_is_stable_and_order_sensitive() -> None:
    from orbitmind.admission.contracts import AdmissionOutcome, AdmissionReasonCode

    a = decision_checksum_source(
        policy_version="operation-admission-v0",
        proposal_fingerprint="0" * 64,
        outcome=AdmissionOutcome.ADMITTED,
        reason_codes=(AdmissionReasonCode.ADMITTED_BY_POLICY,),
        evaluated_at=T0,
        resolved_grant_id=None,
    )
    b = decision_checksum_source(
        policy_version="operation-admission-v0",
        proposal_fingerprint="0" * 64,
        outcome=AdmissionOutcome.DENIED,
        reason_codes=(AdmissionReasonCode.FORBIDDEN_OPERATION_KIND,),
        evaluated_at=T0,
        resolved_grant_id=None,
    )
    assert a != b


def test_authority_finding_consistency_is_enforced() -> None:
    with pytest.raises(PydanticValidationError):
        # authorized without a resolved referenced required grant
        AuthorityFinding(required=False, referenced=False, resolved=False, authorized=True)
    with pytest.raises(PydanticValidationError):
        # resolved_grant_id without resolved=True
        AuthorityFinding(
            required=True,
            referenced=True,
            resolved=False,
            authorized=False,
            resolved_grant_id="grant-00000001",
        )


def test_parse_admission_json_fails_closed() -> None:
    with pytest.raises(AdmissionContractError):
        parse_admission_json(OperationProposal, '{"not":"a valid proposal"}')
