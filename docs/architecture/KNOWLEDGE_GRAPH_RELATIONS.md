# Knowledge Graph Relations

A **lightweight relational** knowledge graph stored in `memory_graph_edges` — **no
Neo4j, no executable query language** (Phase 3B exclusion).

## Edges (`GraphEdge`)
Typed, provenance-bearing, timestamped:
`(from_kind, from_id) --edge_kind--> (to_kind, to_id)`, `source`, optional `weight`.

`GraphEdgeKind`: `has-orbit`, `sourced-from`, `supported-by`, `contains`, `mentions`,
`related-to`, `contradicts`, `produced`, `derives-from`, `cites`.

`EntityKind` (typed entity references — memory is not tightly coupled to every domain
table): `document`, `chunk`, `concept`, `claim`, `evidence`, `space-object`,
`satellite-mission`, `orbital-element-source`, `small-body`, `close-approach`,
`source-policy`, `verification-finding`, `visual-artifact`.

Example relations:
```
space-object → has-orbit    → orbit-record
satellite    → sourced-from → CelesTrak
small-body   → sourced-from → JPL
claim        → supported-by → evidence
document     → contains     → chunk
chunk        → mentions     → concept
concept      → related-to   → concept
claim        → contradicts  → claim
mission      → produced     → scientific-result
```

## Traversal (`GraphService.neighbors`)
**Bounded and cycle-safe**: BFS over out- and in-edges with a `visited` set, a clamped
maximum depth (≤3), a per-node fan-out limit, and a global neighbor cap (truncation is
reported via `truncated`). There is no arbitrary user-supplied traversal query. Verified
by `test_graph_traversal_is_bounded_and_cycle_safe` (a cycle `A→B→A` terminates).
