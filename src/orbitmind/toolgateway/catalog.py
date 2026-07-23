"""Immutable code-owned descriptor catalog; it contains no adapters."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from orbitmind.toolgateway.contracts import (
    AdapterKind,
    GatewayExternalCommunicationPolicy,
    GatewayFilesystemPolicy,
    GatewayNetworkPolicy,
    GatewayProcessPolicy,
    GatewayRiskClass,
    ToolAvailability,
    ToolClass,
    ToolDescriptor,
)


@dataclass(frozen=True, slots=True)
class DescriptorResolution:
    descriptor: ToolDescriptor | None
    tool_registered: bool


def _descriptor(
    tool_id: str,
    name: str,
    description: str,
    tool_class: ToolClass,
    schema: str,
    filesystem: GatewayFilesystemPolicy,
    approval: bool,
    availability: ToolAvailability,
) -> ToolDescriptor:
    return ToolDescriptor(
        tool_id=tool_id,
        tool_version="1.0.0",
        display_name=name,
        description=description,
        tool_class=tool_class,
        adapter_kind=AdapterKind.LOCAL_DETERMINISTIC,
        input_schema_identifier=schema,
        output_schema_identifier="governance_evidence",
        risk_class=GatewayRiskClass.LOW,
        network_policy=GatewayNetworkPolicy.FORBIDDEN,
        filesystem_policy=filesystem,
        process_policy=GatewayProcessPolicy.FORBIDDEN,
        external_communication_policy=GatewayExternalCommunicationPolicy.FORBIDDEN,
        human_approval_requirement=approval,
        availability=availability,
    )


_DESCRIPTORS = (
    _descriptor(
        "repository_file_reader",
        "Repository File Reader",
        "Registered repository read descriptor.",
        ToolClass.REPOSITORY_READ,
        "repository_read_request",
        GatewayFilesystemPolicy.READ_ONLY_REPOSITORY,
        False,
        ToolAvailability.AVAILABLE,
    ),
    _descriptor(
        "local_validation_runner",
        "Local Validation Runner",
        "Registered validation descriptor requiring approval.",
        ToolClass.LOCAL_VALIDATION,
        "local_validation_request",
        GatewayFilesystemPolicy.NONE,
        True,
        ToolAvailability.AVAILABLE,
    ),
    _descriptor(
        "repository_tree_lister",
        "Repository Tree Lister",
        "Registered disabled repository read descriptor.",
        ToolClass.REPOSITORY_READ,
        "repository_tree_request",
        GatewayFilesystemPolicy.READ_ONLY_REPOSITORY,
        False,
        ToolAvailability.DISABLED,
    ),
)
_CATALOG = {(item.tool_id, item.tool_version): item for item in _DESCRIPTORS}
if len(_CATALOG) != len(_DESCRIPTORS):
    raise RuntimeError("tool descriptor identities must be unique")
BUILTIN_TOOL_CATALOG: Final = MappingProxyType(_CATALOG)


def resolve_descriptor(tool_id: str, tool_version: str) -> DescriptorResolution:
    return DescriptorResolution(
        BUILTIN_TOOL_CATALOG.get((tool_id, tool_version)), tool_id in registered_tool_ids()
    )


def registered_tool_ids() -> tuple[str, ...]:
    return tuple(sorted({tool_id for tool_id, _ in BUILTIN_TOOL_CATALOG}))
