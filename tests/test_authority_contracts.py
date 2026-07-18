"""Contract tests for the U7.0 authority domain (strict, immutable, canonical)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from orbitmind.authority.contracts import (
    AUTHORITY_CONTRACT_SCHEMA_VERSION,
    MAX_GRANT_VALIDITY,
    ApprovalDecision,
    ApprovalDecisionOutcome,
    ApprovalRequest,
    AuthorityContractError,
    AuthorityEvaluationDecision,
    AuthorityEvaluationRequest,
    AuthorityReasonCode,
    AuthorityScope,
    CapabilityGrant,
    DelegationPolicy,
    OperatorReference,
    RevocationRecord,
    ScopeConstraint,
    SubjectReference,
    SubjectType,
    ValidityWindow,
    canonical_authority_json,
    parse_authority_json,
)

T0 = datetime(2026, 7, 18, 0, 0, tzinfo=UTC)
IST = timezone(timedelta(hours=5, minutes=30))


def _window(**overrides: Any) -> ValidityWindow:
    values: dict[str, Any] = {"valid_from": T0, "expires_at": T0 + timedelta(days=30)}
    values.update(overrides)
    return ValidityWindow(**values)


def _subject() -> SubjectReference:
    return SubjectReference(subject_type=SubjectType.AGENT, subject_id="agent-dev-0001")


def _operator() -> OperatorReference:
    return OperatorReference(subject_id="operator-piyush-1")


def _scope(**overrides: Any) -> AuthorityScope:
    values: dict[str, Any] = {
        "resource_type": "repository",
        "resource_id": "orbitmind-main",
        "constraints": (ScopeConstraint(name="ref", value="rev-abc123"),),
    }
    values.update(overrides)
    return AuthorityScope(**values)


def _request(**overrides: Any) -> ApprovalRequest:
    values: dict[str, Any] = {
        "request_id": "req-00000001",
        "owner_id": "owner-piyush-01",
        "requested_by": "owner-piyush-01",
        "subject": _subject(),
        "capability": "repository_read",
        "scope": _scope(),
        "purpose": "Read one pinned revision for review evidence.",
        "policy_version": "authority-policy-v1",
        "requested_at": T0,
        "validity": _window(),
    }
    values.update(overrides)
    return ApprovalRequest(**values)


def _decision(**overrides: Any) -> ApprovalDecision:
    request = _request()
    values: dict[str, Any] = {
        "decision_id": "dec-00000001",
        "request_id": request.request_id,
        "owner_id": request.owner_id,
        "decided_by": _operator(),
        "outcome": ApprovalDecisionOutcome.APPROVED,
        "decided_at": T0,
        "reason": "Approved for one bounded review.",
        "subject": request.subject,
        "capability": request.capability,
        "scope": request.scope,
        "purpose": request.purpose,
        "policy_version": request.policy_version,
        "validity": request.validity,
    }
    values.update(overrides)
    return ApprovalDecision(**values)


def _grant(**overrides: Any) -> CapabilityGrant:
    decision = _decision()
    values: dict[str, Any] = {
        "grant_id": "grant-00000001",
        "owner_id": decision.owner_id,
        "request_id": decision.request_id,
        "decision_id": decision.decision_id,
        "issued_by": _operator(),
        "issued_at": T0,
        "subject": decision.subject,
        "capability": decision.capability,
        "scope": decision.scope,
        "purpose": decision.purpose,
        "policy_version": decision.policy_version,
        "validity": decision.validity,
    }
    values.update(overrides)
    return CapabilityGrant(**values)


# --- strict parsing and rejection --------------------------------------------


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _request(surprise="nope")
    with pytest.raises(ValidationError):
        SubjectReference(subject_type=SubjectType.AGENT, subject_id="agent-dev-0001", extra="x")


def test_implicit_coercion_is_rejected() -> None:
    # str for enum, int for str, str for datetime: all rejected in strict mode.
    with pytest.raises(ValidationError):
        SubjectReference(subject_type="agent", subject_id="agent-dev-0001")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        _request(purpose=123)
    with pytest.raises(ValidationError):
        _window(valid_from="2026-07-18T00:00:00Z")


def test_naive_timestamps_are_rejected_everywhere() -> None:
    naive = datetime(2026, 7, 18, 0, 0)
    with pytest.raises(ValidationError):
        _window(valid_from=naive)
    with pytest.raises(ValidationError):
        _request(requested_at=naive)
    with pytest.raises(ValidationError):
        _decision(decided_at=naive)
    with pytest.raises(ValidationError):
        _grant(issued_at=naive)


def test_timestamps_normalize_to_utc() -> None:
    request = _request(requested_at=T0.astimezone(IST))
    assert request.requested_at == T0
    assert request.requested_at.tzinfo == UTC


@pytest.mark.parametrize(
    "bad_id",
    ["", "short", "Has-Upper", "under_score", "-leading", "trailing-", "wild*card", "a" * 70],
)
def test_identifier_grammar_is_canonical(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        _request(request_id=bad_id)


def test_no_wildcard_subject_capability_or_scope() -> None:
    with pytest.raises(ValidationError):
        SubjectReference(subject_type=SubjectType.AGENT, subject_id="*")
    with pytest.raises(ValidationError):
        _request(capability="*")
    with pytest.raises(ValidationError):
        _scope(resource_id="*")
    with pytest.raises(ValidationError):
        _scope(resource_id="repo/*")
    with pytest.raises(ValidationError):
        ScopeConstraint(name="ref", value="*")


def test_approval_and_issuance_actors_must_be_operator_references() -> None:
    assert _decision().decided_by == _operator()
    assert _grant().issued_by == _operator()
    with pytest.raises(ValidationError):
        OperatorReference(subject_type=SubjectType.AGENT, subject_id="agent-dev-0001")
    with pytest.raises(ValidationError):
        _decision(decided_by=_subject())
    with pytest.raises(ValidationError):
        _grant(issued_by=_subject())


def test_strings_are_bounded() -> None:
    with pytest.raises(ValidationError):
        _request(purpose="x" * 301)
    with pytest.raises(ValidationError):
        _decision(reason="x" * 301)


def test_purpose_rejects_paths_urls_and_control_characters() -> None:
    for bad in (
        "see https://example.com",
        "..\\escape",
        "two/level",
        "line\nbreak",
        "tab\tseparated",
        "star * burst",
        "del\x7fchar",
        "nel\x85line",
        "line" + chr(0x2028) + "separator",
        "para" + chr(0x2029) + "separator",
        "bidi" + chr(0x202E) + "override",
        "zero" + chr(0x200B) + "width",
    ):
        with pytest.raises(ValidationError):
            _request(purpose=bad)


def test_dot_dot_is_rejected_uniformly() -> None:
    with pytest.raises(ValidationError):
        ScopeConstraint(name="ref", value="a..b")
    with pytest.raises(ValidationError):
        _request(policy_version="policy..v1")
    with pytest.raises(ValidationError):
        _scope(resource_id="a..b")


def test_scope_constraints_unique_and_sorted() -> None:
    scope = _scope(
        constraints=(
            ScopeConstraint(name="zeta", value="z1"),
            ScopeConstraint(name="alpha", value="a1"),
        )
    )
    assert [constraint.name for constraint in scope.constraints] == ["alpha", "zeta"]
    with pytest.raises(ValidationError):
        _scope(
            constraints=(
                ScopeConstraint(name="ref", value="a"),
                ScopeConstraint(name="ref", value="b"),
            )
        )


# --- validity semantics -------------------------------------------------------


def test_validity_requires_strict_ordering() -> None:
    with pytest.raises(ValidationError):
        _window(expires_at=T0)
    with pytest.raises(ValidationError):
        _window(expires_at=T0 - timedelta(seconds=1))


def test_no_perpetual_grant_structural_cap() -> None:
    assert timedelta(days=366) == MAX_GRANT_VALIDITY
    with pytest.raises(ValidationError):
        _window(expires_at=T0 + MAX_GRANT_VALIDITY + timedelta(seconds=1))
    boundary = _window(expires_at=T0 + MAX_GRANT_VALIDITY)
    assert boundary.expires_at - boundary.valid_from == MAX_GRANT_VALIDITY


def test_validity_interval_is_half_open() -> None:
    window = _window()
    assert window.contains(window.valid_from)
    assert window.contains(window.expires_at - timedelta(seconds=1))
    assert not window.contains(window.expires_at)
    assert not window.contains(window.valid_from - timedelta(seconds=1))


# --- immutability and structure ------------------------------------------------


def test_models_are_immutable() -> None:
    request = _request()
    with pytest.raises(ValidationError):
        request.purpose = "changed"  # type: ignore[misc]
    grant = _grant()
    with pytest.raises(ValidationError):
        grant.capability = "deploy"  # type: ignore[misc]


def test_delegation_vocabulary_is_prohibited_only() -> None:
    assert [policy.value for policy in DelegationPolicy] == ["prohibited"]
    assert _grant().delegation is DelegationPolicy.PROHIBITED
    with pytest.raises(ValidationError):
        _grant(delegation="allowed")


def test_grant_schema_has_no_secret_command_or_import_fields() -> None:
    field_names = set(CapabilityGrant.model_fields)
    forbidden_fragments = ("secret", "token", "credential", "command", "callable", "import")
    for name in field_names:
        for fragment in forbidden_fragments:
            assert fragment not in name, name
    assert field_names == {
        "schema_version",
        "grant_id",
        "owner_id",
        "request_id",
        "decision_id",
        "issued_by",
        "issued_at",
        "subject",
        "capability",
        "scope",
        "purpose",
        "policy_version",
        "validity",
        "delegation",
    }


def test_reason_codes_are_exactly_the_stable_vocabulary() -> None:
    assert {code.value for code in AuthorityReasonCode} == {
        "authorized",
        "approval_not_approved",
        "approval_grant_mismatch",
        "subject_mismatch",
        "capability_mismatch",
        "scope_mismatch",
        "purpose_mismatch",
        "not_yet_valid",
        "expired",
        "revoked",
        "policy_version_mismatch",
        "delegation_prohibited",
        "malformed_authority_chain",
    }


def test_decision_consistency_is_enforced() -> None:
    with pytest.raises(ValidationError):
        AuthorityEvaluationDecision(
            evaluation_id="eval-0000001",
            evaluation_time=T0,
            authorized=True,
            reason_code=AuthorityReasonCode.EXPIRED,
            grant_id="grant-00000001",
            detail="inconsistent",
        )
    with pytest.raises(ValidationError):
        AuthorityEvaluationDecision(
            evaluation_id="eval-0000001",
            evaluation_time=T0,
            authorized=True,
            reason_code=AuthorityReasonCode.AUTHORIZED,
            grant_id=None,
            detail="authorized without grant reference",
        )
    with pytest.raises(ValidationError):
        AuthorityEvaluationDecision(
            evaluation_id="eval-0000001",
            evaluation_time=T0,
            authorized=False,
            reason_code=AuthorityReasonCode.EXPIRED,
            grant_id="grant-00000001",
            detail="forged detail with an untrusted instruction",
        )
    with pytest.raises(ValidationError):
        AuthorityEvaluationDecision(
            evaluation_id="eval-0000001",
            evaluation_time=T0,
            authorized=False,
            reason_code=AuthorityReasonCode.MALFORMED_AUTHORITY_CHAIN,
            grant_id="grant-00000001",
            detail="The supplied authority chain is not internally consistent.",
        )


def test_parsed_evaluation_decision_cannot_forge_detail() -> None:
    payload = {
        "schema_version": AUTHORITY_CONTRACT_SCHEMA_VERSION,
        "evaluation_id": "eval-0000001",
        "evaluation_time": T0.isoformat(),
        "authorized": False,
        "reason_code": AuthorityReasonCode.EXPIRED.value,
        "grant_id": "grant-00000001",
        "detail": "forged detail with an untrusted instruction",
    }
    with pytest.raises(AuthorityContractError):
        parse_authority_json(AuthorityEvaluationDecision, json.dumps(payload))


def test_evaluation_request_normalizes_revocations() -> None:
    def _revocation(rid: str, effective: datetime) -> RevocationRecord:
        return RevocationRecord(
            revocation_id=rid,
            grant_id="grant-00000001",
            owner_id="owner-piyush-01",
            revoked_by="owner-piyush-01",
            effective_at=effective,
            recorded_at=effective,
            reason="Revocation ordering test.",
        )

    later = _revocation("rvk-00000002", T0 + timedelta(days=2))
    earlier = _revocation("rvk-00000001", T0 + timedelta(days=1))
    request = AuthorityEvaluationRequest(
        evaluation_id="eval-0000001",
        owner_id="owner-piyush-01",
        evaluation_time=T0,
        subject=_subject(),
        capability="repository_read",
        scope=_scope(),
        purpose="Read one pinned revision for review evidence.",
        policy_version="authority-policy-v1",
        approval_request=_request(),
        approval_decision=_decision(),
        grant=_grant(),
        revocations=(later, earlier),
    )
    assert [record.revocation_id for record in request.revocations] == [
        "rvk-00000001",
        "rvk-00000002",
    ]
    with pytest.raises(ValidationError):
        AuthorityEvaluationRequest(
            evaluation_id="eval-0000001",
            owner_id="owner-piyush-01",
            evaluation_time=T0,
            subject=_subject(),
            capability="repository_read",
            scope=_scope(),
            purpose="Read one pinned revision for review evidence.",
            policy_version="authority-policy-v1",
            approval_request=_request(),
            approval_decision=_decision(),
            grant=_grant(),
            revocations=(earlier, earlier),
        )


# --- canonical serialization ----------------------------------------------------


def test_canonical_serialization_is_deterministic_and_sorted() -> None:
    first = canonical_authority_json(_grant())
    second = canonical_authority_json(_grant())
    assert first == second
    payload = json.loads(first)
    assert list(payload) == sorted(payload)
    assert payload["schema_version"] == AUTHORITY_CONTRACT_SCHEMA_VERSION
    assert ": " not in first and ", " not in first  # compact separators


def test_canonical_round_trip_preserves_equality() -> None:
    grant = _grant()
    restored = CapabilityGrant.model_validate_json(grant.model_dump_json())
    assert restored == grant
    assert canonical_authority_json(restored) == canonical_authority_json(grant)


def test_parse_authority_json_is_fail_closed_and_typed() -> None:
    grant = _grant()
    parsed = parse_authority_json(CapabilityGrant, grant.model_dump_json())
    assert parsed == grant
    with pytest.raises(AuthorityContractError) as excinfo:
        parse_authority_json(CapabilityGrant, '{"grant_id": "nope"}')
    assert excinfo.value.code == "authority_contract_error"
    with pytest.raises(AuthorityContractError):
        parse_authority_json(ApprovalRequest, "not json at all")
