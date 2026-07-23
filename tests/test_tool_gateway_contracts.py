"""Contract and catalog proofs for the non-executing Tool Gateway v0."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

import pytest
from pydantic import ValidationError

import orbitmind.toolgateway.catalog as catalog
from orbitmind.toolgateway.catalog import BUILTIN_TOOL_CATALOG, registered_tool_ids
from orbitmind.toolgateway.contracts import (
    GatewayDecision,
    GatewayNetworkPolicy,
    GatewayOutcome,
    GatewayReasonCode,
    ToolDescriptor,
    ToolInvocationProposal,
    descriptor_checksum,
    fingerprint_source,
    tool_gateway_canonical_json,
)

T0 = datetime(2026, 7, 22, tzinfo=UTC)


def _proposal_payload() -> dict[str, Any]:
    return {
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


def test_catalog_is_immutable_canonical_and_has_unique_identities() -> None:
    keys = tuple(BUILTIN_TOOL_CATALOG)
    assert registered_tool_ids() == tuple(sorted(registered_tool_ids()))
    assert len(BUILTIN_TOOL_CATALOG) == 3
    assert len(keys) == len(set(keys)) == len(catalog._DESCRIPTORS)
    with pytest.raises(TypeError):
        BUILTIN_TOOL_CATALOG[("duplicate", "1.0.0")] = next(  # type: ignore[index]
            iter(BUILTIN_TOOL_CATALOG.values())
        )


def test_descriptor_is_frozen_and_rejects_unsupported_schema_and_policy() -> None:
    descriptor = BUILTIN_TOOL_CATALOG[("repository_file_reader", "1.0.0")]
    with pytest.raises(ValidationError):
        ToolDescriptor(**(descriptor.model_dump() | {"schema_version": "future"}))
    with pytest.raises(ValidationError):
        ToolDescriptor(**(descriptor.model_dump() | {"network_policy": "allowed"}))
    with pytest.raises((ValidationError, FrozenInstanceError)):
        descriptor.availability = descriptor.availability  # type: ignore[misc]
    assert descriptor.network_policy is GatewayNetworkPolicy.FORBIDDEN


def test_descriptor_checksum_is_stable_and_domain_separated() -> None:
    descriptor = BUILTIN_TOOL_CATALOG[("repository_file_reader", "1.0.0")]
    canonical = tool_gateway_canonical_json(descriptor)
    checksum = descriptor_checksum(descriptor)
    assert checksum == descriptor_checksum(
        ToolDescriptor.model_validate(json.loads(canonical), strict=False)
    )
    assert checksum != sha256(canonical.encode("utf-8")).hexdigest()
    assert (
        checksum
        == sha256(b"orbitmind-tool-descriptor-v1\x00" + canonical.encode("utf-8")).hexdigest()
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("purpose", "bad..value"),
        ("purpose", "https://example.invalid"),
        ("purpose", "bad\\value"),
        ("purpose", "bad*value"),
        ("purpose", "bad\nvalue"),
        ("input_schema_reference", "bad/value"),
        ("tool_id", "bad-tool"),
    ],
)
def test_proposal_rejects_forbidden_grammar(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        ToolInvocationProposal(**(_proposal_payload() | {field: value}))


def test_proposal_is_closed_strict_and_schema_pinned() -> None:
    payload = _proposal_payload()
    assert ToolInvocationProposal(**payload).idempotency_key == "gateway-key-1"
    with pytest.raises(ValidationError):
        ToolInvocationProposal(**payload, command="no")
    with pytest.raises(ValidationError):
        ToolInvocationProposal(**(payload | {"schema_version": "future"}))
    with pytest.raises(ValidationError):
        ToolInvocationProposal(**(payload | {"requested_at": T0.isoformat()}))


def test_fingerprint_excludes_key_but_binds_trusted_identity_and_tool_version() -> None:
    from orbitmind.toolgateway.contracts import GatewayEvaluationContext

    proposal = ToolInvocationProposal(**_proposal_payload())
    context = GatewayEvaluationContext(
        authoritative_owner_id=proposal.owner_id,
        authoritative_actor_id=proposal.actor_id,
        evaluated_at=T0,
    )
    same_content_new_key = ToolInvocationProposal(
        **(_proposal_payload() | {"idempotency_key": "gateway-key-2"})
    )
    assert fingerprint_source(proposal, context) == fingerprint_source(
        same_content_new_key, context
    )
    changed_owner = context.model_copy(update={"authoritative_owner_id": "owner-0002"})
    changed_actor = context.model_copy(update={"authoritative_actor_id": "actor-0002"})
    changed_version = proposal.model_copy(update={"tool_version": "2.0.0"})
    assert fingerprint_source(proposal, context) != fingerprint_source(proposal, changed_owner)
    assert fingerprint_source(proposal, context) != fingerprint_source(proposal, changed_actor)
    assert fingerprint_source(proposal, context) != fingerprint_source(changed_version, context)


def test_decision_detail_is_pinned_to_primary_reason() -> None:
    valid = GatewayDecision(
        outcome=GatewayOutcome.DENIED,
        primary_reason_code=GatewayReasonCode.UNKNOWN_TOOL,
        reason_codes=(GatewayReasonCode.UNKNOWN_TOOL,),
        evaluated_at=T0,
        detail="The requested tool is not registered.",
    )
    assert valid.detail == "The requested tool is not registered."
    with pytest.raises(ValidationError):
        GatewayDecision(
            outcome=GatewayOutcome.DENIED,
            primary_reason_code=GatewayReasonCode.UNKNOWN_TOOL,
            reason_codes=(GatewayReasonCode.UNKNOWN_TOOL,),
            evaluated_at=T0,
            detail="unknown tool",
        )
