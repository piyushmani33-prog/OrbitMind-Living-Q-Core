"""Exact 13-row precedence proof for the pure Tool Gateway policy."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

import orbitmind.toolgateway.policy as gateway_policy
from orbitmind.toolgateway.catalog import DescriptorResolution, resolve_descriptor
from orbitmind.toolgateway.contracts import (
    AdmissionFinding,
    GatewayEvaluationContext,
    GatewayOutcome,
    GatewayReasonCode,
    ToolInvocationProposal,
)
from orbitmind.toolgateway.policy import evaluate_gateway_proposal

T0 = datetime(2026, 7, 22, tzinfo=UTC)


def _proposal(**updates: object) -> ToolInvocationProposal:
    values: dict[str, object] = {
        "proposal_id": "proposal-0001",
        "owner_id": "owner-0001",
        "actor_id": "actor-0001",
        "admission_id": "admission-0001",
        "tool_id": "repository_file_reader",
        "tool_version": "1.0.0",
        "input_schema_reference": "repository_read_request",
        "purpose": "Read repository evidence",
        "requested_at": T0,
        "idempotency_key": "gateway-key-1",
    }
    values.update(updates)
    return ToolInvocationProposal(**values)


def _context(**updates: object) -> GatewayEvaluationContext:
    values: dict[str, object] = {
        "authoritative_owner_id": "owner-0001",
        "authoritative_actor_id": "actor-0001",
        "evaluated_at": T0,
    }
    values.update(updates)
    return GatewayEvaluationContext(**values)


def _finding(**updates: object) -> AdmissionFinding:
    values: dict[str, object] = {
        "found": True,
        "admitted": True,
        "actor_id": "actor-0001",
        "operation_kind": "read_repository",
        "admission_record_identity": "a" * 64,
    }
    values.update(updates)
    return AdmissionFinding(**values)


@pytest.mark.parametrize(
    "reason",
    list(GatewayReasonCode),
    ids=lambda reason: reason.value,
)
def test_each_precedence_row_independently(reason: GatewayReasonCode) -> None:
    proposal = _proposal()
    context = _context()
    finding = _finding()
    resolution = resolve_descriptor(proposal.tool_id, proposal.tool_version)
    kind_patch: dict[object, object] | None = None

    if reason is GatewayReasonCode.OWNER_MISMATCH:
        proposal = _proposal(owner_id="owner-0002")
    elif reason is GatewayReasonCode.ACTOR_MISMATCH:
        proposal = _proposal(actor_id="actor-0002")
    elif reason is GatewayReasonCode.UNKNOWN_TOOL:
        proposal = _proposal(tool_id="unknown_tool")
        resolution = DescriptorResolution(descriptor=None, tool_registered=False)
    elif reason is GatewayReasonCode.UNSUPPORTED_TOOL_VERSION:
        proposal = _proposal(tool_version="2.0.0")
        resolution = DescriptorResolution(descriptor=None, tool_registered=True)
    elif reason is GatewayReasonCode.FORBIDDEN_TOOL_CLASS:
        kind_patch = {}
    elif reason is GatewayReasonCode.INPUT_SCHEMA_MISMATCH:
        proposal = _proposal(input_schema_reference="different_schema")
    elif reason is GatewayReasonCode.TOOL_UNAVAILABLE:
        proposal = _proposal(
            tool_id="repository_tree_lister", input_schema_reference="repository_tree_request"
        )
        resolution = resolve_descriptor(proposal.tool_id, proposal.tool_version)
    elif reason is GatewayReasonCode.ADMISSION_NOT_FOUND:
        finding = AdmissionFinding(found=False, admitted=False)
    elif reason is GatewayReasonCode.ADMISSION_NOT_ADMITTED:
        finding = _finding(admitted=False)
    elif reason is GatewayReasonCode.ADMISSION_ACTOR_MISMATCH:
        finding = _finding(actor_id="actor-0002")
    elif reason is GatewayReasonCode.ADMISSION_OPERATION_MISMATCH:
        finding = _finding(operation_kind="run_local_validation")
    elif reason is GatewayReasonCode.EXPLICIT_HUMAN_APPROVAL_REQUIRED:
        proposal = _proposal(
            tool_id="local_validation_runner",
            input_schema_reference="local_validation_request",
        )
        finding = _finding(operation_kind="run_local_validation")
        resolution = resolve_descriptor(proposal.tool_id, proposal.tool_version)

    with (
        patch.dict(gateway_policy._KIND, kind_patch, clear=True)
        if kind_patch is not None
        else _null()
    ):
        first = evaluate_gateway_proposal(proposal, context, finding, resolution)
        second = evaluate_gateway_proposal(proposal, context, finding, resolution)

    expected_outcome = (
        GatewayOutcome.ELIGIBLE
        if reason is GatewayReasonCode.ELIGIBLE_BY_POLICY
        else GatewayOutcome.APPROVAL_REQUIRED
        if reason is GatewayReasonCode.EXPLICIT_HUMAN_APPROVAL_REQUIRED
        else GatewayOutcome.DENIED
    )
    assert first == second
    assert first.outcome is expected_outcome
    assert first.primary_reason_code is reason
    assert first.reason_codes == (reason,)
    assert first.reason_codes[-1] is first.primary_reason_code


class _null:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_args: object) -> None:
        return None


def test_first_failure_wins_in_documented_order() -> None:
    proposal = _proposal(owner_id="owner-0002", actor_id="actor-0002", tool_id="unknown_tool")
    decision = evaluate_gateway_proposal(
        proposal,
        _context(),
        AdmissionFinding(found=False, admitted=False),
        DescriptorResolution(descriptor=None, tool_registered=False),
    )
    assert decision.reason_codes == (GatewayReasonCode.OWNER_MISMATCH,)


def test_availability_is_evaluated_from_the_current_resolution() -> None:
    proposal = _proposal()
    available = resolve_descriptor(proposal.tool_id, proposal.tool_version)
    assert available.descriptor is not None
    disabled = DescriptorResolution(
        descriptor=available.descriptor.model_copy(update={"availability": "disabled"}),
        tool_registered=True,
    )
    assert (
        evaluate_gateway_proposal(proposal, _context(), _finding(), available).primary_reason_code
        is GatewayReasonCode.ELIGIBLE_BY_POLICY
    )
    assert (
        evaluate_gateway_proposal(proposal, _context(), _finding(), disabled).primary_reason_code
        is GatewayReasonCode.TOOL_UNAVAILABLE
    )
