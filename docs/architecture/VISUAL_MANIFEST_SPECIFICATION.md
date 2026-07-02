# Visual Manifest Specification — OrbitMind Living Q-Core

## Purpose and status

This is a Phase 5.2 documentation-only specification.

The visual manifest is a future read-only discovery/index contract. It
describes how existing persisted mission artifacts, sidecars, authenticated
optimization artifacts, observation study-chain records, integrity summaries,
and provenance/evidence metadata could be represented safely.

This specification does not implement an API. It does not implement schemas,
routes, migrations, rendering, reports, dashboards, graphs, maps, exports, or
UI. It must conform to [VISUAL_INTELLIGENCE_BOUNDARY.md](VISUAL_INTELLIGENCE_BOUNDARY.md).

Phase 5.9 status: the initial visual manifest family is closed with two
implemented domain-specific read-only routes:

- `GET /api/v1/visual-manifests/mission/{mission_id}`;
- `GET /api/v1/visual-manifests/optimization-benchmark/{benchmark_id}`.

No generic dispatcher or mutation routes exist. `observation-study`,
`integrity-summary`, and `memory-evidence` remain reserved/deferred and require
separate planning and review before implementation.

## Manifest is not authority

A visual manifest is not verification by itself.

A visual manifest is not approval.

A visual manifest is not a signed receipt.

A visual manifest is not operational access.

A visual manifest is not taskability.

A visual manifest is not command readiness.

A visual manifest is not certification.

A visual manifest is not real-world authenticity.

A visual manifest is not quantum authority.

It only indexes safe, already persisted records.

## Existing surface divergence

Current visual and visual-adjacent surfaces do not expose metadata in a single
shape:

- mission artifact metadata currently exposes relative artifact and sidecar
  paths;
- optimization artifact views deliberately avoid on-disk path exposure and use
  safer artifact/checksum style metadata;
- observation study-chain and integrity-summary APIs expose safe read-only
  records, not rendered visuals;
- memory, provenance, and evidence records are future visual inputs, not a
  reviewed visual manifest surface.

The manifest specification must normalize these surfaces before any API exists.

| Domain | Current surface | Path/locator behavior | Manifest target convention |
| --- | --- | --- | --- |
| Mission artifacts | `altitude_vs_time`, `ground_track`, artifact metadata, and JSON sidecars | Relative artifact and sidecar paths exist today | Treat relative paths as bounded legacy/domain-specific behavior |
| Optimization artifacts | Authenticated artifact metadata for benchmark runs | Handle/checksum style metadata; on-disk paths are not exposed | Prefer handle/checksum metadata as the stricter convention |
| Observation studies | Study-chain and integrity-summary records | Safe IDs, checksums, status, limitations, and disclaimers | Use IDs/checksums/status only; do not expose raw internals |
| Memory/provenance/evidence metadata | Future visual inputs | Safe IDs, citations, labels, and source references are available through domain-specific records | Use safe IDs, citations, and labels, not raw internal records |

## Locator and path policy

Content-addressed or stable handles are the canonical manifest locator pattern.

Preferred locators include artifact id, checksum id, source record id, or other
reviewed stable handles.

Raw absolute filesystem paths are prohibited. The artifacts root value itself
must never be exposed.

Relative locators are allowed only as bounded, domain-specific legacy
compatibility for surfaces that already expose them, such as mission artifacts.
Relative locators must never include path traversal. Relative locators must not
become the preferred cross-domain convention.

Future APIs should converge toward handle-based/path-free discovery where
possible.

Sidecar paths should not be exposed as raw navigation paths unless a future safe
API contract explicitly allows it.

## Manifest field categories

These field categories are future specification only.

### Manifest identity

Allowed category examples:

- schema version;
- manifest kind;
- generated/read timestamp;
- source domain;
- scope id;
- owner id only where the underlying source is owner-scoped.

### Visual item identity

Allowed category examples:

- stable item id;
- item type;
- media type;
- artifact/checksum identifiers;
- source record ids.

### Provenance and linkage

Allowed category examples:

- mission id;
- benchmark id;
- geometry/study/planning ids;
- provenance link ids;
- checksums;
- source identity checksums.

### Scientific context

Allowed category examples:

- canonical epistemic status;
- verification state;
- integrity or record-consistency state;
- source/freshness/test-only labels;
- units;
- limitations;
- disclaimer.

Disclaimer and limitation text should reuse canonical source or domain
disclaimers where possible, not invent drift-prone manifest-only language.

### Presentation hints

Allowed category examples:

- visual role;
- title/label;
- ordering/grouping;
- related items;
- diagnostic-vs-primary marker.

Presentation hints do not add scientific authority.

### Access metadata

Allowed category examples:

- safe artifact handle;
- checksum handle;
- reviewed source record handle;
- bounded relative locator only where already exposed and explicitly allowed.

Access metadata must not expose raw absolute paths or unsafe sidecar internals.

## Excluded and unsafe fields

The manifest must not expose:

- raw local filesystem paths;
- absolute artifacts-root value;
- database URLs;
- SQL;
- stack traces;
- environment values;
- internal correlation keys;
- internal idempotency keys;
- provider secrets;
- credentials;
- raw sidecar JSON unless each field is explicitly reviewed safe;
- raw `result_json`;
- raw `request_json`;
- raw `link_json`;
- planning snapshots;
- provenance snapshots;
- raw TLE lines;
- raw samples by default;
- raw intervals by default;
- receipt envelopes;
- signing internals;
- unredacted quantum evidence internals;
- command claims;
- taskability claims;
- approval claims;
- certification claims;
- operational scheduling claims;
- real-world asset-control claims.

## Domain projection notes

### Mission artifacts

Mission artifact projections can expose safe artifact identity, type, checksum,
units, verification state, source/freshness labels, and a bounded locator or
handle.

Mission artifact projections must not imply live satellite status. They must not
expose absolute filesystem paths.

### Small-body artifacts

Small-body artifact projections can expose bounded static artifact identity,
model-estimate labeling, checksum, limitations, and source references.

Small-body artifact projections must not imply high-fidelity ephemeris, direct
observation, or impact probability.

### Optimization artifacts

Optimization artifact projections can expose selected timeline, objective,
feasibility, and diagnostic artifact identities plus checksum handles.

Optimization artifact projections must preserve no-general-quantum-advantage
wording. They must not expose receipt internals, signing internals, or
unredacted quantum evidence internals.

### Observation study chains

Observation study-chain projections can expose safe ids, checksums, statuses,
disclaimers, and linkage between geometry, eligibility, planning, and
provenance records.

Observation study-chain projections must not expose raw planning/provenance
snapshots. They must not imply operational access.

### Integrity summaries

Integrity-summary projections can expose record-consistency status and checks.

Integrity-summary projections must preserve success-only/fail-closed meaning.
They must not provide a failed-summary shape. They must not imply real-world
authenticity.

### Memory/provenance/evidence metadata

Memory, provenance, and evidence metadata projections can expose safe ids,
labels, citations, evidence kinds, and source references.

They must not treat generated answer synthesis as verified fact. They must not
expose raw internal graph/query structures by default.

## Future API considerations

This section is planning only. Phase 5.2 itself did not implement an API.

The implemented initial routes are domain-specific, read-only, and strict about
unknown parameters. Future additional-domain manifest APIs should delegate to
existing domain/query services. They should reject unknown parameters. They
should avoid recomputation. They should avoid mutation. They should return safe
manifest DTOs only.

Future additional-domain APIs should not expose raw sidecars, raw paths, raw
`result_json`, SQL internals, or provider secrets.

PostgreSQL validation becomes required for additional future API/query
implementation that touches persisted records.

## Scientific-honesty boundaries

Manifests index already persisted records; they do not verify truth by
themselves.

Visuals interpret already persisted records.

Sample TLE data is not live satellite status.

Offline observation geometry is not live tracking.

Study-chain views are not operational access.

Integrity summaries are read-time record consistency, not real-world
authenticity.

Reports are not approval or signed receipts.

Dashboards are not command surfaces.

There is no taskability.

There is no command readiness.

There is no certification.

There is no quantum authority.

There is no general quantum advantage claim.

Generated answers are not treated as verified fact.

There are no confidence percentages on deterministic calculations.

There is no raw filesystem path leakage.

There is no SQL/internal `result_json` leakage.

There are no unredacted sidecar internals unless explicitly safe.

## Future gates

Future gates are planning checkpoints only:

- [Phase 5.3 API contract planning/specification](VISUAL_MANIFEST_API_CONTRACT.md),
  still docs/spec first;
- additional read-only manifest domain implementation only after API contract
  review;
- [static report specification](STATIC_REPORT_SPECIFICATION.md) after
  manifest semantics;
- provenance/study graph specification after manifest identity/linking
  semantics;
- map/orbit planning before Leaflet/CesiumJS;
- dashboard planning before frontend work.

Phase 5.3 should not jump directly to route implementation. Each later gate
needs separate planning/review.

## Explicit exclusions for Phase 5.2

Phase 5.2 does not add:

- API route;
- schema class;
- router change;
- migration;
- persistence change;
- runtime behavior change;
- rendering;
- artifact regeneration;
- report/PDF/export generator;
- CesiumJS;
- Leaflet;
- D3;
- React dashboard;
- frontend;
- live TLE retrieval;
- live provider intake;
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
