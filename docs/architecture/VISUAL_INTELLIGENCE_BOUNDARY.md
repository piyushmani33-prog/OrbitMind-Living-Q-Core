# Visual Intelligence Boundary — OrbitMind Living Q-Core

## Purpose and scope

Phase 5 visual intelligence is read-only interpretation of already persisted
records, artifacts, sidecars, provenance, evidence, and observation study-chain
data.

This document defines the boundary before any visual manifest, API, report,
dashboard, graph, map, orbit view, or UI implementation.

Phase 5.1 does not implement rendering, regeneration, reports, exports,
frontend work, APIs, or new computation.

## Safe visual inputs

The safe inputs for future visual-intelligence work are existing persisted
records and authenticated metadata:

- persisted mission artifacts and JSON sidecars;
- authenticated optimization artifacts;
- read-only observation study chains;
- read-only observation study chain integrity summaries;
- provenance, claim, evidence, source, and verification metadata.

Visual consumption is a read-only projection. A visual surface may summarize,
filter, arrange, or annotate existing records, but it must not mutate records,
regenerate artifacts, recompute scientific values, or create new scientific
authority.

Authenticated artifacts, receipts, or read-time consistency checks must never be
elevated into operational authorization, command authority, approval, a new
signed-receipt claim, or real-world authenticity.

## Existing artifact and data inventory

Existing visual and visual-adjacent sources include:

- mission `altitude_vs_time.png` artifacts;
- mission `ground_track.png` artifacts;
- mission JSON sidecars;
- artifact checksums;
- source references;
- explicit units;
- verification status;
- small-body bounded static artifacts;
- optimization selected timeline artifacts;
- optimization objective comparison artifacts;
- optimization feasibility comparison artifacts;
- optimization diagnostic artifacts;
- benchmark summary JSON;
- read-only observation study chain data;
- read-only observation study chain integrity-summary data.

Mission and small-body visuals are stored artifacts, not live feeds. Study-chain
and integrity-summary records are currently visual inputs, not existing rendered
visuals.

## Visual honesty labels

Visual surfaces must preserve the canonical epistemic labels from the governance
model:

- `verified-fact`
- `deterministic-calculation`
- `model-estimate`
- `hypothesis`
- `assumption`
- `unknown`
- `rejected`

Additional visual descriptors may appear as artifact or provenance layers, but
they are not replacements for the canonical epistemic taxonomy. Examples:

- record consistency;
- source-asserted evidence;
- diagnostic artifact.

Do not redefine or fork the canonical epistemic taxonomy. Do not introduce
confidence percentages for deterministic calculations. Do not imply that a
chart, map, graph, report, or dashboard is more certain than the underlying
persisted record.

## Prohibited visual claims

Visual surfaces must not claim or imply:

- live tracking;
- live satellite status from sample TLE data;
- real-time operational access;
- taskability;
- command readiness;
- spacecraft command authority;
- operational scheduling authority;
- approval;
- signed receipt;
- certification;
- real-world authenticity;
- quantum authority;
- general quantum advantage;
- generated answer treated as verified fact;
- confidence percentage on deterministic calculations;
- live or real-data implication from sample inputs.

## Boundary invariants

All visual surfaces must preserve artifact-root containment.

Visual or manifest surfaces must not leak raw local filesystem paths, SQL
internals, unredacted sidecar internals, or internal `result_json` structures
unless an explicit safe API contract later allows it.

Visuals must preserve source and freshness labels. Sample TLE data remains
sample, stale, or test data unless clearly sourced otherwise. Offline
observation geometry is not live tracking.

Observation study chain views are not operational access. Integrity summaries
are read-time record consistency only, not real-world authenticity.

Reports and dashboards, if later implemented, are not approvals, signed
receipts, or command surfaces.

## Future gates

Future gates are planning checkpoints only, not active implementation:

- Phase 5.2 visual manifest planning/specification;
- future read-only visual manifest API, only after manifest semantics are
  approved;
- static report specification, not PDF/export implementation yet;
- provenance/study graph semantics before D3 or graph UI;
- map/orbit UI planning before Leaflet/CesiumJS work;
- dashboard planning before frontend work.

Each gate requires separate planning and review before implementation.

## Explicit exclusions for Phase 5.1

Phase 5.1 does not add:

- CesiumJS;
- Leaflet;
- D3;
- React dashboard;
- report generator;
- PDF/export system;
- new rendering;
- visual artifact regeneration;
- new API route;
- database migration;
- artifact storage redesign;
- live provider intake;
- live TLE retrieval;
- Space-Track;
- live CelesTrak fetch;
- NASA Earthdata;
- operational scheduling;
- command workflow;
- taskability workflow;
- approval workflow;
- signed receipt workflow;
- certification workflow;
- real-world asset control;
- Quantum Studio;
- Qiskit implementation;
- IBM Quantum;
- AWS Braket;
- Azure Quantum;
- autonomous agents;
- async workers;
- batch compute;
- UI/mobile work;
- deployment work;
- memory/consciousness layer.

## Review triggers

A new review is required before:

- adding a visual manifest schema/API;
- exposing artifact or sidecar metadata through a new public route;
- rendering study-chain or integrity-summary visuals;
- adding reports or exports;
- adding map/orbit views;
- adding D3/provenance graphs;
- adding dashboards;
- introducing live data into a visual surface;
- introducing any provider-backed visual surface.
