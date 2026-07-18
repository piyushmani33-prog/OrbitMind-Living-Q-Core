# ADR-0031 — Laboratory Foundation Core Primitive: Reuse Mission

- **Status:** Accepted (2026-07-18)

## Context
U6 introduces the Laboratory Framework foundation: versioned manifests, a
capability-declaration model, a deterministic registry, a read-only catalog API
and a visual Laboratory Workbench. Future laboratories (Development, Research,
Quantum, Robotics, Space, Manufacturing) and, later, bounded agents will need a
universal governed work primitive. Candidates evaluated: **Mission**,
**Experiment**, **Blueprint**, **Capsule**, and a thin **Work Unit** wrapping a
typed Mission payload.

The existing `orbitmind.mission.Mission` aggregate already provides everything
the governed spine requires: stable identity (`id`), preserved immutable raw
input (`raw_request`, SR-03), a validated normalized request, an explicit
lifecycle (`received → validated → running → completed/failed`), epistemic
labelling, and existing relationships to evidence (artifacts + checksums),
provenance records, verification findings, replay surfaces, persistence and
human review. Every current OrbitMind workflow (orbit propagation, mission
windows, observation planning, optimization benchmarks) already flows through
it or through services governed by the same spine.

## Decision
**Reuse Mission as the universal governed work primitive for laboratories.**
No new central object (Experiment/Blueprint/Capsule/Work Unit) is introduced in
this slice, and the existing Mission implementation is not rewritten.

Laboratory manifests bind to Mission indirectly and declaratively:

- `accepted_goal_categories` names the kinds of future goals a laboratory would
  accept as missions (bounded kebab-case tokens, no code references);
- `required_deterministic_services` names the existing spine services any
  future laboratory execution must use (mission lifecycle, provenance,
  verification, artifact persistence);
- `compatibility.mission_contract` records this ADR's binding in the manifest.

Documented relationships of the primitive (current + future extension points):

- **Identity / immutable inputs / lifecycle / failure:** the Mission aggregate
  as implemented today (UUID id, verbatim `raw_request`, status enum with
  explicit `failed`; cancellation would extend the status enum in a future
  reviewed change, not this one).
- **Result / evidence / provenance / replay:** existing artifact records,
  checksums, provenance records, verification findings and deterministic
  replay classification remain the only evidence path.
- **Approval:** existing human-approval steps; future laboratory capability
  approvals attach to missions as new governed steps, never replacing them.
- **Laboratory relationship (future):** a mission gains an optional laboratory
  association in a future slice; nothing persists it today.
- **Adapter / agent relationship (future):** adapters and bounded agents would
  submit *proposals and evidence into* a mission; they never become
  authoritative for persisted truth, checksums, provenance, approval, policy,
  merge, deployment, publishing, hardware or external communication.
- **Child work (future):** decomposition would be modelled as missions linked
  by a parent reference added through a reviewed migration — not in this slice.
- **Archive / versioning:** missions are persisted append-style with recorded
  status; manifests carry their own `laboratory_version` + `schema_version`.

## Alternatives considered
- **New `Experiment`/`Blueprint`/`Capsule` object** — rejected: duplicates the
  Mission lifecycle, splits provenance/evidence into a second system, and
  contradicts the modular-monolith spine (CLAUDE.md invariant 1) for no
  functional gain. Novelty alone is not a reason.
- **Thin Work Unit wrapper now** — rejected for this slice: nothing executes in
  the Laboratory foundation, so a wrapper would be dead abstraction. The
  manifest's `accepted_goal_categories` keeps the seam open; a typed wrapper
  can still be introduced later if a real laboratory workflow proves the need.

## Consequences
- No persistence migration, no new schema, no Mission rewrite in U6.
- The Laboratory domain (`orbitmind.laboratory`) stays metadata-only and does
  not import mission execution code; the binding is by declared contract.
- Future laboratory execution slices must extend Mission (associations,
  capability approvals, child links) through reviewed ADRs + migrations.

## Review trigger
Revisit when the first laboratory *execution* slice (or the Multi-Agent
Runtime) is designed — specifically if goal categories need typed payload
schemas or mission decomposition, which would justify the thin Work Unit
wrapper evaluated here.
