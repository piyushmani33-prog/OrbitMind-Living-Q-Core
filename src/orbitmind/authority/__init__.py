"""U7 Authority Control Plane — pure domain contracts and evaluation (U7.0).

Strict, immutable, deterministic authority contracts: approval requests,
approval decisions, scoped expiring capability grants, revocations, and
side-effect-free authority evaluation with stable reason codes.

This package is a **decision layer only**. It contains no persistence, API,
UI, network, filesystem, subprocess, tool, agent, credential, or execution
surface, and nothing in it can perform — or authorize the performance of — a
real operation. An ``authorized`` evaluation result is a decision record, not
a credential.

Non-negotiable distinctions preserved here structurally:

- a capability declaration is not permission;
- an approval request is not approval;
- an approval decision is not execution;
- grant possession alone is not sufficient authority (evaluation is exact and
  fail-closed);
- delegation is prohibited in v1;
- rejection, expiry, revocation, mismatch, or uncertainty fails closed.
"""

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
from orbitmind.authority.evaluation import EVALUATION_PRECEDENCE, evaluate_authority

__all__ = (
    "AUTHORITY_CONTRACT_SCHEMA_VERSION",
    "EVALUATION_PRECEDENCE",
    "MAX_GRANT_VALIDITY",
    "ApprovalDecision",
    "ApprovalDecisionOutcome",
    "ApprovalRequest",
    "AuthorityContractError",
    "AuthorityEvaluationDecision",
    "AuthorityEvaluationRequest",
    "AuthorityReasonCode",
    "AuthorityScope",
    "CapabilityGrant",
    "DelegationPolicy",
    "OperatorReference",
    "RevocationRecord",
    "ScopeConstraint",
    "SubjectReference",
    "SubjectType",
    "ValidityWindow",
    "canonical_authority_json",
    "evaluate_authority",
    "parse_authority_json",
)
