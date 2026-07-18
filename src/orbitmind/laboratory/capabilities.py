"""Capability declarations for laboratories.

A capability declaration is *descriptive metadata*: it states what kind of
governed work a laboratory is designed to request in the future, and under
which approval posture such a request would fall. It is **never** a grant.

The model structurally separates six ideas that must not be conflated:

- **capability** — a named kind of sensitive or governed action;
- **permission** — a grant to perform it (no grant type exists in this slice);
- **tool availability** — whether a concrete tool is connected (always false here);
- **adapter availability** — whether an adapter is connected (always false here);
- **approval requirement** — the human-approval posture the action would require;
- **execution authority** — who may actually execute (none is conferred here).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CAPABILITY_IS_NOT_PERMISSION = (
    "Declaring a capability does not grant permission to use it. Capability "
    "declarations are catalog metadata; every sensitive action remains subject "
    "to explicit human approval and to the existing OrbitMind governance spine."
)


class LabCapability(StrEnum):
    """Named kinds of governed laboratory action (a bounded vocabulary)."""

    REPOSITORY_READ = "repository_read"
    REPOSITORY_WRITE = "repository_write"
    TEST_EXECUTE = "test_execute"
    LOCAL_PROCESS_EXECUTE = "local_process_execute"
    NETWORK_RESEARCH = "network_research"
    EXTERNAL_AI_CONSULT = "external_ai_consult"
    QUANTUM_SIMULATOR_EXECUTE = "quantum_simulator_execute"
    CLOUD_QUANTUM_SUBMIT = "cloud_quantum_submit"
    CAMERA_STILL_CAPTURE = "camera_still_capture"
    HARDWARE_CONTROL = "hardware_control"
    PUBLISH = "publish"
    DEPLOY = "deploy"


class ApprovalPosture(StrEnum):
    """Human-approval posture a capability would require if ever exercised."""

    LOCALLY_SAFE = "locally_safe"
    MISSION_APPROVAL_REQUIRED = "mission_approval_required"
    ACTION_APPROVAL_REQUIRED = "action_approval_required"
    PROHIBITED_BY_DEFAULT = "prohibited_by_default"


class CapabilityDeterminism(StrEnum):
    """Whether exercising the capability would be a deterministic operation."""

    DETERMINISTIC = "deterministic"
    NON_DETERMINISTIC = "non_deterministic"


class ExecutionAuthority(StrEnum):
    """Execution authority conferred by a declaration. Only ``NONE`` exists in v1."""

    NONE = "none"


class CapabilityDeclaration(BaseModel):
    """One declared (not granted) capability of a laboratory.

    ``tool_connected``, ``adapter_connected`` and ``execution_authority`` are
    pinned to their only truthful v1 values by ``Literal`` types: no manifest
    can claim a connected tool, a connected adapter, or any execution authority
    in this slice without a reviewed schema change.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: LabCapability
    approval_posture: ApprovalPosture
    determinism: CapabilityDeterminism
    summary: str = Field(min_length=1, max_length=300)
    tool_connected: Literal[False] = False
    adapter_connected: Literal[False] = False
    execution_authority: Literal[ExecutionAuthority.NONE] = ExecutionAuthority.NONE

    @property
    def grants_permission(self) -> bool:
        """A declaration never grants permission. Structurally always ``False``."""
        return False
