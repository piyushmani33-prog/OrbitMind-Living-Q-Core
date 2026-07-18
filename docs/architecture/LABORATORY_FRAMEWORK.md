# OrbitMind Laboratory Framework — Foundation v1 (U6)

The Laboratory Framework is the catalog-and-governance layer beneath the future
laboratories (Development, Research, Quantum, Robotics, Space, Manufacturing)
and, later, the Multi-Agent Runtime. **Foundation v1 is metadata + a visual
surface only**: versioned immutable manifests, a capability-declaration model,
a deterministic in-process registry, a read-only catalog API and the visual
Laboratory Workbench. Nothing in it executes work, loads plugins, spawns
agents, or grants authority.

Related: [ADR-0031](decisions/ADR-0031-laboratory-foundation-core-primitive.md)
(core primitive: reuse Mission), [MODULE_BOUNDARIES.md](MODULE_BOUNDARIES.md),
[SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md), and
[ADR-0032](decisions/ADR-0032-laboratory-schema-compatibility-and-catalog-digest.md)
(schema, compatibility, and catalog identity policy).

## 1. Architecture

```text
orbitmind.laboratory            (domain; Pydantic-only, framework-independent)
  capabilities.py               capability vocabulary + declaration model
  contracts.py                  LaboratoryManifest (versioned, immutable)
  registry.py                   LaboratoryRegistry (deterministic, in-process)
  catalog.py                    built-in Development Laboratory + labelled
                                static projections (roadmap, mission flow,
                                evidence chain, safety plane, offline boundary)

orbitmind.api                   (existing app; U6 additions)
  container.py                  owns one registry instance per container
  routers/laboratory.py         GET /api/v1/laboratories[/{id}],
                                GET /workbench/laboratory,
                                GET /assets/laboratory.js
  presentation/laboratory.py    deterministic HTML/SVG/CSS projection
  assets/laboratory.js          reviewed progressive-enhancement controller
```

Module dependency rule is unchanged: `laboratory` imports only `orbitmind.core`
(+ the bare package for `__version__`) and Pydantic. The API layer imports the
domain, never the reverse — enforced by `tests/test_architecture_boundaries.py`
and `tests/test_laboratory_architecture.py`.

## 2. Core primitive

**Mission is the universal governed work primitive** (ADR-0031). Manifests bind
to it declaratively via `accepted_goal_categories`,
`required_deterministic_services` and `compatibility.mission_contract`. No new
work object, no Mission rewrite, no migration.

## 3. Laboratory Manifest semantics

`LaboratoryManifest` (`schema_version = "laboratory-manifest-v1"`) is a strict,
frozen, versioned contract: identity, domain, description, implementation
status, capability declarations, goal/artifact/evidence categories, postures
(network / hardware / persistence), approval gates, replay requirement,
verification requirements, resource boundaries, compatibility, mandatory
limitations and deprecation state.

Manifest rules:

- **Metadata, never authority.** No import paths, commands, code, secrets or
  credentials can appear; category tokens are bounded kebab-case (no dots,
  slashes or spaces), enforced by validation.
- **Immutable + strict.** `frozen=True`, `extra="forbid"`, bounded strings and
  collections; registration hands out the same frozen instance forever.
- **Deterministic serialization.** Collections normalize to sorted order at
  validation time; `canonical_json()` uses sorted keys, compact UTF-8 JSON, and
  is byte-stable for equal manifests.
- **Honest by construction.** `limitations` is mandatory (min 1 statement);
  `tool_connected`/`adapter_connected`/`execution_authority` are pinned by
  `Literal` types to `False`/`False`/`"none"` — a manifest *cannot* claim a
  connected tool or any authority in v1 without a reviewed schema change.

### 3.1 Schema evolution and framework compatibility

The current supported manifest schema is the explicit string
`laboratory-manifest-v1`. Parsing is fail-closed: an earlier, future, wrong-type,
or otherwise unsupported schema is rejected without automatic translation or
upgrade. Additive schema evolution requires an explicitly supported new minor
schema; breaking evolution requires a new major schema. Supporting either needs
code, tests, compatibility review, and approved migration/translation rules where
applicable. A schema version is metadata only and grants no capability,
permission, installation, activation, or execution authority.

The Laboratory Framework contract version is separately `1.0.0`; it is not the
OrbitMind package version and not the manifest schema. Its dependency-free
canonical grammar is bounded ASCII `MAJOR.MINOR.PATCH`, with exactly three
non-negative decimal components, no leading zeros (apart from `0`), signs,
whitespace, prerelease/build suffixes, or expression syntax.

Each manifest additionally carries immutable structured
`framework_compatibility` metadata:

```text
minimum_inclusive <= current_framework_contract < maximum_exclusive
```

Both bounds are required and the minimum must be strictly less than the maximum.
The built-in Development Laboratory declares `[1.0.0, 2.0.0)`. This declaration
does not load code, discover plugins, grant permissions, or activate a laboratory.
The older `compatibility` object remains the descriptive package-baseline and
Mission-binding statement; it is not repurposed as the enforcement range.

## 4. Capability vs permission

The model separates six ideas that must never be conflated: **capability**
(named kind of governed action), **permission** (a grant — no grant type exists
in this slice), **tool availability**, **adapter availability**, **approval
requirement** (`locally_safe`, `mission_approval_required`,
`action_approval_required`, `prohibited_by_default`) and **execution
authority** (always `none` in v1).

> Declaring a capability does not grant permission to use it.

That principle is a module constant (`CAPABILITY_IS_NOT_PERMISSION`), a
structural property (`grants_permission` is always `False`), an API field and a
prominent statement on the Workbench page. No permission grants or execution
APIs exist in this slice.

## 5. Registry behavior

`LaboratoryRegistry` is an isolated in-process catalog: explicit
`register(manifest)` only, unsupported schemas and incompatible framework ranges
rejected before duplicate identifiers are checked or registry state is changed, deterministic sorted
`list_manifests()`/`get()`, safe 404-style error for unknown ids, immutable
records. There is **no** filesystem scanning, entry-point loading, dynamic
import, network access, persistence, background thread or module-level
singleton (each `AppContainer` builds its own instance via
`build_default_registry()`). Registration ≠ installation ≠ activation ≠
authorization. One built-in laboratory is registered: the Development
Laboratory (`implementation_status = catalog-foundation`). The five other
laboratories exist only as labelled roadmap projections
(`planned — no runtime implementation`) and are **not** registry members.

Registration failures use stable typed domain errors to distinguish an unsupported
schema, an incompatible framework range, a duplicate identifier, and a non-manifest
input. Rejection is atomic: no fallback, automatic upgrade, code loading, or
partial registration occurs.

## 5.1 Catalog identity

The catalog has a deterministic `catalog_digest` projection with explicit format
`laboratory-catalog-digest-v1`, algorithm `sha256`, and a lowercase 64-hex value.
It hashes only the registered manifest catalog semantics: the catalog schema,
supported manifest schema identities, framework contract version, every manifest
semantic field (including its schema and framework range), and manifests sorted by
`laboratory_id`.

Canonicalization uses JSON-compatible data, sorted keys, compact separators,
stable Unicode UTF-8, and the exact domain separator
`orbitmind.laboratory.catalog.v1\0` before SHA-256. It excludes timestamps,
process state, paths, registration order, caches, credentials, and the digest
itself. The digest is an identity/checksum only: it is **not** a signature,
approval, trust claim, readiness result, or execution authority.

## 6. Visual Laboratory Workbench

`GET /workbench/laboratory` renders a self-contained control-room page from the
same `LaboratoryCatalogProjection` the API serves (the page embeds the payload
in a `<template>`; a test asserts byte-level equality with
`GET /api/v1/laboratories`). Regions: laboratory constellation (inline SVG;
implemented = solid, planned = dashed), selected-laboratory focus panels,
governed mission flow (exists-today vs future stages), capability/authority
matrix, evidence-and-replay chain (labelled architecture projection — no
fabricated mission data), safety/governance plane (16 human-approval gates) and
the offline/connected boundary.

Behavior: server-rendered and fully readable without JavaScript (all panels
visible). The reviewed `laboratory.js` controller progressively enhances
selection (buttons + SVG links, `aria-pressed`, `hidden`, polite status line),
validates the embedded payload schema and fails safe (leaves everything
visible) on any DOM/payload mismatch. No `innerHTML`, no fetch, no browser
storage, no external assets, `prefers-reduced-motion` respected, keyboard
operable with visible focus states, responsive from 390 px up.

The existing catalog response is already an envelope, so `catalog_digest` is one
additive typed field on the same projection. No digest route, verification route,
compatibility mutation route, or frontend-maintained digest exists; the embedded
Workbench payload remains byte-for-byte the API projection.

## 7. Offline-first operation

The complete experience is local: system font stack, inline CSS, inline SVG,
one same-origin script served from package resources. The page carries the
existing strict CSP (`script-src 'self'`, `connect-src 'none'`) and Workbench
referrer policy. No CDN, fonts, analytics, telemetry, external icons or
network-loaded images. Tests assert the absence of any external URL.

## 8. Security and prompt-injection boundaries

- Existing deterministic services remain authoritative; a laboratory owns no
  independent provenance/approval/identity/replay/policy system.
- Manifests are data. Nothing in a manifest (or in any external document,
  repository, website, model response, image or message a future agent might
  read) can grant tool authority — grants simply do not exist in this layer,
  and the manifest schema cannot express them.
- The catalog API is read-only (GET only, enforced by test), exposes no
  filesystem paths, secrets or fake health, and unknown ids return a sanitized
  404.
- Future agents are bounded workers, never authorities, and every future
  execution must carry bounded identity, inputs, permissions, resources and
  evidence; deterministic replay and non-deterministic re-evaluation stay
  distinct classifications.

## 9. Future Multi-Agent Runtime integration point

The runtime will plug in *behind* the approval gates declared here: agents
propose plans / candidate artifacts / comparisons, request declared
capabilities, and submit evidence into missions. The integration seams are the
manifest's `accepted_goal_categories` + `capabilities` + `approval_gates`, and
ADR-0031's documented Mission extension points. None of that exists yet, and
this document must not be read as claiming it does.

## 10. Explicit exclusions (v1)

No agent runtime, AI conversations, LLM/AI-provider adapters, CrewAI,
child-agent creation, autonomous development, plugin loading, code loading from
manifests, subprocess execution, repository mutation, dependency installation,
external research, cloud quantum, hardware control, camera/microphone,
persistence migration, marketplace, publishing, deployment, self-learning,
knowledge inheritance or self-upgrade.

## 11. Known limitations

- One registered laboratory; the other five are roadmap labels only.
- Capability declarations carry no grant/tool/adapter reality yet — every
  matrix cell for authority is truthfully "none".
- The mission-flow and evidence-chain regions are architecture projections of
  the existing spine, not per-mission views; a future slice may link real
  mission evidence.
- Selection state is ephemeral (no persistence, by design).
- Browser-matrix verification is limited to the local harness + one local
  Chromium; no cross-browser CI exists.

## 12. Operator guide — opening the Laboratory

```bash
# from the repository root (offline; SQLite defaults)
.venv\Scripts\python.exe -m uvicorn orbitmind.api.app:app --host 127.0.0.1 --port 8000
```

Then open <http://127.0.0.1:8000/workbench/laboratory> in a local browser.
Read-only API: `GET /api/v1/laboratories` and
`GET /api/v1/laboratories/development-laboratory`. The page states its own
boundary: everything shown comes from the deterministic registry and labelled
architectural metadata — no agents, no live telemetry, no execution.
