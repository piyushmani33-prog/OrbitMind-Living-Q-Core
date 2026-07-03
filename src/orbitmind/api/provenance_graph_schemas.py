"""API wire schemas for read-only provenance study graph projections."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel, ConfigDict

from orbitmind.core.errors import ValidationError
from orbitmind.core.timeutils import utcnow
from orbitmind.observation_studies.models import ObservationStudyChain

PROVENANCE_GRAPH_SCHEMA_VERSION: Literal["provenance-graph-v1"] = "provenance-graph-v1"
PROVENANCE_GRAPH_SOURCE_DOMAIN: Literal["observation-study"] = "observation-study"
PROVENANCE_GRAPH_TYPE: Literal["geometry-planning-chain"] = "geometry-planning-chain"
PROVENANCE_GRAPH_STATUS: Literal["chain-checks-consistent"] = "chain-checks-consistent"
PROVENANCE_GRAPH_OWNER_SCOPE: Literal["trusted-owner-dependency"] = "trusted-owner-dependency"

PROVENANCE_GRAPH_DISCLAIMER = (
    "This provenance study graph is a read-only, non-authoritative projection over an "
    "owner-scoped authenticated observation study chain. A served graph means only that "
    "the owner-scoped study-chain read and integrity checks succeeded. It is not proof "
    "of scientific correctness, not evidence by itself, not complete lineage, not live "
    "tracking, not real-time position authority, not operational access, not taskability, "
    "not command readiness, not approval, not certification, not signed receipt authority, "
    "not an operational recommendation, not autonomous decision-making, not causal proof, "
    "not quantum authority, and not a claim of general quantum advantage."
)
PROVENANCE_GRAPH_LIMITATIONS: tuple[str, ...] = (
    "Provenance study graph v1 is generated on demand and is not persisted as a graph artifact.",
    "Provenance study graph v1 uses the existing owner-scoped observation study chain "
    "read model as its safe input layer; it does not inspect raw persisted payloads, "
    "observational payload streams, orbital element lines, or internal files.",
    "Graph existence means the study-chain read and integrity checks succeeded only; "
    "it is not proof of scientific correctness, complete lineage, operational readiness, "
    "approval, certification, taskability, command readiness, signed receipt authority, "
    "quantum authority, or general quantum advantage.",
    "Edges are projections of recorded relationships only; inferred, heuristic, "
    "model-generated, recommendation, task, and command edges are not included.",
    "Owner isolation is enforced through the trusted owner dependency; client-supplied "
    "owner, principal, or user query parameters are rejected.",
)

AllowedNodeType = Literal[
    "geometry-run",
    "eligibility-provenance",
    "eligibility-set",
    "planning-request",
    "planning-run",
    "observation-plan",
    "provenance-link",
    "integrity-summary",
]
AllowedEdgeType = Literal[
    "eligibility-provenance derived-from geometry-run",
    "eligibility-set uses eligibility-provenance",
    "provenance-link links eligibility-provenance",
    "provenance-link links eligibility-set",
    "provenance-link links planning-request",
    "provenance-link links planning-run",
    "planning-run produced observation-plan",
    "integrity-summary checks observation-study-chain",
]
AllowedProofSource = Literal[
    "recorded-provenance:derived-from-geometry",
    "recorded-fk:eligibility-set-to-provenance",
    "recorded-link:provenance-link-to-eligibility-provenance",
    "recorded-link:provenance-link-to-eligibility-set",
    "recorded-link:provenance-link-to-planning-request",
    "recorded-link:provenance-link-to-planning-run",
    "recorded-fk:planning-run-to-observation-plan",
    "recorded-summary:chain-integrity",
]

_REQUIRED_CHECK_IDS = frozenset(
    {
        "geometry-provenance-checksum",
        "geometry-source-identity",
        "eligibility-window-geometry",
        "planning-link-authenticated",
    }
)
_EDGE_PROOF_SOURCES: Mapping[AllowedEdgeType, AllowedProofSource] = MappingProxyType(
    {
        "eligibility-provenance derived-from geometry-run": (
            "recorded-provenance:derived-from-geometry"
        ),
        "eligibility-set uses eligibility-provenance": (
            "recorded-fk:eligibility-set-to-provenance"
        ),
        "provenance-link links eligibility-provenance": (
            "recorded-link:provenance-link-to-eligibility-provenance"
        ),
        "provenance-link links eligibility-set": (
            "recorded-link:provenance-link-to-eligibility-set"
        ),
        "provenance-link links planning-request": (
            "recorded-link:provenance-link-to-planning-request"
        ),
        "provenance-link links planning-run": "recorded-link:provenance-link-to-planning-run",
        "planning-run produced observation-plan": "recorded-fk:planning-run-to-observation-plan",
        "integrity-summary checks observation-study-chain": "recorded-summary:chain-integrity",
    }
)


class ObservationStudyGraphNodeResponse(BaseModel):
    """One safe node in an owner-scoped observation study graph."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    node_id: str
    node_type: AllowedNodeType
    record_handle: str
    checksum_handle: str | None
    status: tuple[str, ...]
    source: str
    limitations: tuple[str, ...]
    disclaimer: str


class ObservationStudyGraphEdgeResponse(BaseModel):
    """One recorded relationship projection in an observation study graph."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    edge_id: str
    edge_type: AllowedEdgeType
    source: str
    target: str
    proof_source: AllowedProofSource
    limitations: tuple[str, ...]
    disclaimer: str


class ObservationStudyProvenanceGraphResponse(BaseModel):
    """Safe HTTP projection for an observation-study geometry-planning graph.

    The integrity-summary node has no persisted record id. Its node identity is
    pinned to the graph scope handle:
    ``study-graph-node:integrity-summary:{scope_handle}``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["provenance-graph-v1"]
    graph_id: str
    read_at: datetime
    source_domain: Literal["observation-study"]
    graph_type: Literal["geometry-planning-chain"]
    scope_handle: str
    owner_scope: Literal["trusted-owner-dependency"]
    status: Literal["chain-checks-consistent"]
    nodes: tuple[ObservationStudyGraphNodeResponse, ...]
    edges: tuple[ObservationStudyGraphEdgeResponse, ...]
    node_count: int
    edge_count: int
    limitations: tuple[str, ...]
    disclaimer: str

    @classmethod
    def from_chain(
        cls,
        chain: ObservationStudyChain,
        *,
        read_at: datetime | None = None,
    ) -> ObservationStudyProvenanceGraphResponse:
        """Build a graph from the authenticated observation study chain read model.

        This performs no I/O, no recomputation, no provider calls, no sidecar or raw JSON
        reads, no rendering, no file writes, and no mutation.
        """

        _require_passing_checks(chain)
        scope_handle = _scope_handle(chain)
        nodes = _nodes(chain, scope_handle)
        edges = _edges(chain, scope_handle)
        limitations = (*PROVENANCE_GRAPH_LIMITATIONS, *chain.limitations)
        return cls(
            schema_version=PROVENANCE_GRAPH_SCHEMA_VERSION,
            graph_id=f"provenance-study-graph:{scope_handle}:v1",
            read_at=read_at or utcnow(),
            source_domain=PROVENANCE_GRAPH_SOURCE_DOMAIN,
            graph_type=PROVENANCE_GRAPH_TYPE,
            scope_handle=scope_handle,
            owner_scope=PROVENANCE_GRAPH_OWNER_SCOPE,
            status=PROVENANCE_GRAPH_STATUS,
            nodes=nodes,
            edges=edges,
            node_count=len(nodes),
            edge_count=len(edges),
            limitations=limitations,
            disclaimer=PROVENANCE_GRAPH_DISCLAIMER,
        )


def _scope_handle(chain: ObservationStudyChain) -> str:
    return f"observation-study-chain:{chain.geometry.run_id}:{chain.planning.link_record_id}"


def _require_passing_checks(chain: ObservationStudyChain) -> None:
    if not chain.checks or any(not check.passed for check in chain.checks):
        raise ValidationError("study graph withheld because chain integrity checks failed")
    passed_ids = {check.check_id for check in chain.checks if check.passed}
    if not _REQUIRED_CHECK_IDS.issubset(passed_ids):
        raise ValidationError("study graph withheld because chain integrity checks are incomplete")


def _nodes(
    chain: ObservationStudyChain,
    scope_handle: str,
) -> tuple[ObservationStudyGraphNodeResponse, ...]:
    geometry_node = _node(
        node_type="geometry-run",
        record_id=chain.geometry.run_id,
        record_handle=f"observation-geometry-run:{chain.geometry.run_id}",
        checksum_handle=_checksum_handle(chain.geometry.geometry_checksum),
        status=(
            "read-status:authenticated",
            f"epistemic-status:{chain.geometry.epistemic_status}",
        ),
        source="authenticated-read:observation-geometry-run",
    )
    provenance_node = _node(
        node_type="eligibility-provenance",
        record_id=chain.eligibility.provenance_record_id,
        record_handle=f"eligibility-provenance:{chain.eligibility.provenance_record_id}",
        checksum_handle=_checksum_handle(chain.eligibility.provenance_checksum),
        status=(
            "read-status:authenticated",
            f"source-type:{chain.eligibility.source_type}",
            f"source-mode:{chain.eligibility.source_mode}",
            f"verification-status:{chain.eligibility.verification_status}",
        ),
        source="authenticated-read:eligibility-provenance",
    )
    eligibility_node = _node(
        node_type="eligibility-set",
        record_id=chain.eligibility.eligibility_set_record_id,
        record_handle=f"eligibility-set:{chain.eligibility.eligibility_set_record_id}",
        checksum_handle=_checksum_handle(chain.eligibility.eligibility_set_checksum),
        status=(
            "read-status:authenticated",
            f"selected-window-count:{len(chain.eligibility.selected_window_ids)}",
        ),
        source="authenticated-read:eligibility-set",
    )
    planning_request_node = _node(
        node_type="planning-request",
        record_id=chain.planning.planning_request_id,
        record_handle=f"planning-request:{chain.planning.planning_request_id}",
        checksum_handle=_checksum_handle(chain.planning.planning_request_checksum),
        status=(
            "read-status:authenticated",
            f"source-mode:{chain.planning.planning_request_source_mode}",
        ),
        source="authenticated-read:planning-request",
    )
    planning_run_node = _node(
        node_type="planning-run",
        record_id=chain.planning.planning_run_id,
        record_handle=f"planning-run:{chain.planning.planning_run_id}",
        checksum_handle=_checksum_handle(chain.planning.planning_scientific_identity_checksum),
        status=(
            "read-status:authenticated",
            f"planning-status:{chain.planning.planning_status}",
            f"optimality:{chain.planning.optimality_label}",
            f"feasible:{str(chain.planning.feasible).lower()}",
        ),
        source="authenticated-read:planning-run",
    )
    plan_nodes: tuple[ObservationStudyGraphNodeResponse, ...] = ()
    if chain.planning.observation_plan_id is not None:
        plan_nodes = (
            _node(
                node_type="observation-plan",
                record_id=chain.planning.observation_plan_id,
                record_handle=f"observation-plan:{chain.planning.observation_plan_id}",
                checksum_handle=None,
                status=("read-status:authenticated",),
                source="authenticated-read:observation-plan",
            ),
        )
    provenance_link_node = _node(
        node_type="provenance-link",
        record_id=chain.planning.link_record_id,
        record_handle=f"provenance-link:{chain.planning.link_record_id}",
        checksum_handle=_checksum_handle(chain.planning.link_checksum),
        status=("read-status:authenticated", "link-status:authenticated"),
        source="authenticated-read:provenance-link",
    )
    integrity_summary_node = _node(
        node_type="integrity-summary",
        record_id=scope_handle,
        record_handle=scope_handle,
        checksum_handle=None,
        status=(PROVENANCE_GRAPH_STATUS, f"passed-check-count:{len(chain.checks)}"),
        source="authenticated-read:study-chain-integrity",
    )
    return (
        geometry_node,
        provenance_node,
        eligibility_node,
        planning_request_node,
        planning_run_node,
        *plan_nodes,
        provenance_link_node,
        integrity_summary_node,
    )


def _node(
    *,
    node_type: AllowedNodeType,
    record_id: str,
    record_handle: str,
    checksum_handle: str | None,
    status: tuple[str, ...],
    source: str,
) -> ObservationStudyGraphNodeResponse:
    return ObservationStudyGraphNodeResponse(
        node_id=f"study-graph-node:{node_type}:{record_id}",
        node_type=node_type,
        record_handle=record_handle,
        checksum_handle=checksum_handle,
        status=status,
        source=source,
        limitations=PROVENANCE_GRAPH_LIMITATIONS,
        disclaimer=PROVENANCE_GRAPH_DISCLAIMER,
    )


def _edges(
    chain: ObservationStudyChain,
    scope_handle: str,
) -> tuple[ObservationStudyGraphEdgeResponse, ...]:
    geometry = f"study-graph-node:geometry-run:{chain.geometry.run_id}"
    provenance = f"study-graph-node:eligibility-provenance:{chain.eligibility.provenance_record_id}"
    eligibility = f"study-graph-node:eligibility-set:{chain.eligibility.eligibility_set_record_id}"
    planning_request = f"study-graph-node:planning-request:{chain.planning.planning_request_id}"
    planning_run = f"study-graph-node:planning-run:{chain.planning.planning_run_id}"
    provenance_link = f"study-graph-node:provenance-link:{chain.planning.link_record_id}"
    integrity_summary = f"study-graph-node:integrity-summary:{scope_handle}"
    edges = [
        _edge(
            edge_type="eligibility-provenance derived-from geometry-run",
            source=provenance,
            target=geometry,
        ),
        _edge(
            edge_type="eligibility-set uses eligibility-provenance",
            source=eligibility,
            target=provenance,
        ),
        _edge(
            edge_type="provenance-link links eligibility-provenance",
            source=provenance_link,
            target=provenance,
        ),
        _edge(
            edge_type="provenance-link links eligibility-set",
            source=provenance_link,
            target=eligibility,
        ),
        _edge(
            edge_type="provenance-link links planning-request",
            source=provenance_link,
            target=planning_request,
        ),
        _edge(
            edge_type="provenance-link links planning-run",
            source=provenance_link,
            target=planning_run,
        ),
        _edge(
            edge_type="integrity-summary checks observation-study-chain",
            source=integrity_summary,
            target=scope_handle,
        ),
    ]
    if chain.planning.observation_plan_id is not None:
        edges.append(
            _edge(
                edge_type="planning-run produced observation-plan",
                source=planning_run,
                target=f"study-graph-node:observation-plan:{chain.planning.observation_plan_id}",
            )
        )
    return tuple(sorted(edges, key=lambda edge: (edge.edge_type, edge.source, edge.target)))


def _edge(
    *,
    edge_type: AllowedEdgeType,
    source: str,
    target: str,
) -> ObservationStudyGraphEdgeResponse:
    return ObservationStudyGraphEdgeResponse(
        edge_id=f"study-graph-edge:{edge_type}:{source}:{target}",
        edge_type=edge_type,
        source=source,
        target=target,
        proof_source=_EDGE_PROOF_SOURCES[edge_type],
        limitations=PROVENANCE_GRAPH_LIMITATIONS,
        disclaimer=PROVENANCE_GRAPH_DISCLAIMER,
    )


def _checksum_handle(checksum: str) -> str:
    if len(checksum) != 64 or any(char not in "0123456789abcdef" for char in checksum.lower()):
        raise ValidationError("study graph withheld because a checksum is malformed")
    return f"sha256:{checksum}"
