"""Pure deterministic gateway policy. It records eligibility; it never invokes tools."""

from __future__ import annotations

from orbitmind.toolgateway.catalog import DescriptorResolution
from orbitmind.toolgateway.contracts import (
    _DETAILS,
    AdmissionFinding,
    GatewayDecision,
    GatewayEvaluationContext,
    GatewayOutcome,
    GatewayReasonCode,
    ToolAvailability,
    ToolClass,
    ToolInvocationProposal,
)

_KIND = {
    ToolClass.REPOSITORY_READ: "read_repository",
    ToolClass.LOCAL_VALIDATION: "run_local_validation",
}


def evaluate_gateway_proposal(
    proposal: ToolInvocationProposal,
    context: GatewayEvaluationContext,
    finding: AdmissionFinding,
    resolution: DescriptorResolution,
) -> GatewayDecision:
    reasons: list[GatewayReasonCode] = []
    descriptor = resolution.descriptor
    if proposal.owner_id != context.authoritative_owner_id:
        reasons.append(GatewayReasonCode.OWNER_MISMATCH)
    elif proposal.actor_id != context.authoritative_actor_id:
        reasons.append(GatewayReasonCode.ACTOR_MISMATCH)
    elif not resolution.tool_registered:
        reasons.append(GatewayReasonCode.UNKNOWN_TOOL)
    elif descriptor is None:
        reasons.append(GatewayReasonCode.UNSUPPORTED_TOOL_VERSION)
    elif descriptor.tool_class not in _KIND:
        reasons.append(GatewayReasonCode.FORBIDDEN_TOOL_CLASS)
    elif proposal.input_schema_reference != descriptor.input_schema_identifier:
        reasons.append(GatewayReasonCode.INPUT_SCHEMA_MISMATCH)
    elif descriptor.availability is not ToolAvailability.AVAILABLE:
        reasons.append(GatewayReasonCode.TOOL_UNAVAILABLE)
    elif not finding.found:
        reasons.append(GatewayReasonCode.ADMISSION_NOT_FOUND)
    elif not finding.admitted:
        reasons.append(GatewayReasonCode.ADMISSION_NOT_ADMITTED)
    elif finding.actor_id != context.authoritative_actor_id:
        reasons.append(GatewayReasonCode.ADMISSION_ACTOR_MISMATCH)
    elif finding.operation_kind != _KIND[descriptor.tool_class]:
        reasons.append(GatewayReasonCode.ADMISSION_OPERATION_MISMATCH)
    elif descriptor.human_approval_requirement:
        reasons.append(GatewayReasonCode.EXPLICIT_HUMAN_APPROVAL_REQUIRED)
    else:
        reasons.append(GatewayReasonCode.ELIGIBLE_BY_POLICY)
    primary = reasons[-1]
    outcome = (
        GatewayOutcome.ELIGIBLE
        if primary is GatewayReasonCode.ELIGIBLE_BY_POLICY
        else GatewayOutcome.APPROVAL_REQUIRED
        if primary is GatewayReasonCode.EXPLICIT_HUMAN_APPROVAL_REQUIRED
        else GatewayOutcome.DENIED
    )
    return GatewayDecision(
        outcome=outcome,
        primary_reason_code=primary,
        reason_codes=tuple(reasons),
        evaluated_at=context.evaluated_at,
        detail=_DETAILS[primary],
    )
