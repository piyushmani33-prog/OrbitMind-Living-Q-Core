"""Lightweight relational knowledge graph (no Neo4j; bounded, cycle-safe traversal)."""

from __future__ import annotations

from orbitmind.memory.models import (
    EntityKind,
    EntityReference,
    GraphEdge,
    GraphEdgeKind,
    GraphNeighbor,
    GraphNeighborsResult,
)
from orbitmind.memory.repository import SqlAlchemyMemoryRepository

_MAX_DEPTH = 3
_MAX_NEIGHBORS = 200
_PER_NODE_LIMIT = 100


class GraphService:
    """Stores typed edges and performs bounded, cycle-safe neighbor traversal."""

    def add_edge(self, edge: GraphEdge, repo: SqlAlchemyMemoryRepository) -> GraphEdge:
        repo.add_graph_edge(edge)
        return edge

    def neighbors(
        self,
        entity_id: str,
        repo: SqlAlchemyMemoryRepository,
        *,
        depth: int = 1,
        limit: int = _MAX_NEIGHBORS,
    ) -> GraphNeighborsResult:
        depth = max(1, min(depth, _MAX_DEPTH))
        limit = max(1, min(limit, _MAX_NEIGHBORS))
        visited: set[str] = {entity_id}
        frontier = [entity_id]
        neighbors: list[GraphNeighbor] = []
        truncated = False

        for _level in range(depth):
            next_frontier: list[str] = []
            for node in frontier:
                for edge in repo.edges_from(node, _PER_NODE_LIMIT):
                    neighbors.append(
                        GraphNeighbor(
                            edge_kind=GraphEdgeKind(edge.edge_kind),
                            direction="out",
                            entity=EntityReference(
                                kind=EntityKind(edge.to_kind), entity_id=edge.to_id
                            ),
                            source=edge.source,
                        )
                    )
                    if edge.to_id not in visited:
                        visited.add(edge.to_id)
                        next_frontier.append(edge.to_id)
                    if len(neighbors) >= limit:
                        truncated = True
                        break
                if truncated:
                    break
                for edge in repo.edges_to(node, _PER_NODE_LIMIT):
                    neighbors.append(
                        GraphNeighbor(
                            edge_kind=GraphEdgeKind(edge.edge_kind),
                            direction="in",
                            entity=EntityReference(
                                kind=EntityKind(edge.from_kind), entity_id=edge.from_id
                            ),
                            source=edge.source,
                        )
                    )
                    if edge.from_id not in visited:
                        visited.add(edge.from_id)
                        next_frontier.append(edge.from_id)
                    if len(neighbors) >= limit:
                        truncated = True
                        break
                if truncated:
                    break
            if truncated:
                break
            frontier = next_frontier

        return GraphNeighborsResult(
            entity_id=entity_id, depth=depth, neighbors=neighbors[:limit], truncated=truncated
        )
