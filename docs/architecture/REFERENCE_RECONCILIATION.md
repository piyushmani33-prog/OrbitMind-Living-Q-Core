# Reference Reconciliation — OrbitMind Living Q-Core

Status: **Provisional.** The authoritative vision DOCX/PDF are **absent** (see
[`../reference/REFERENCE_MANIFEST.md`](../reference/REFERENCE_MANIFEST.md), risk
R-001). This matrix therefore reconciles the **current implementation** against the
**owner build prompts** (Phase 0/1 + Phase 2), which are the approved specification
in lieu of the documents. It must be re-validated against the real documents when
they arrive.

## Classification legend
`implemented` · `partially implemented` · `planned` · `deferred` ·
`intentionally rejected` · `contradicted` · `unclear`

## Aspirational-language translation policy
Per the prompt, marketing/aspirational language is **not** treated as literal
engineering requirements. Translations used throughout:

| Aspirational phrase | Bounded, testable capability |
|---|---|
| "Living / self-evolving Q-Core" | Versioned, human-approved, test-gated improvements; no self-deploy (lifecycle: lab→quarantine→testing→risk review→human approval→live). |
| "Knows everything / universal science cortex" | A modular monolith with per-domain deterministic tools; explicit `unknown` epistemic status when out of scope. |
| "Quantum brain" | Bounded, simulator-first Qiskit adapter, off the mission path, with a mandatory classical baseline. |
| "108 brains / agent swarm" | One Prime Orchestrator dynamically invoking domain modules; **intentionally rejected** as a literal swarm. |

## Traceability matrix

| # | Capability (from prompt) | Status | Evidence / location | Notes |
|---|--------------------------|--------|---------------------|-------|
| 1 | Permanent mission spine | **implemented** | `orchestration/orchestrator.py`, `docs/architecture/MISSION_LIFECYCLE.md` | Full spine traversed by the orbital slice; "Human Approval" node is a policy no-op for read-only compute (modeled via `ApprovalRecord`). |
| 2 | Modular-monolith architecture | **implemented** | `src/orbitmind/*`, ADR-0001, `MODULE_BOUNDARIES.md` | Downward dependency rule enforced in review; import-linter planned. |
| 3 | Satellite/Earth-orbit intelligence mission | **implemented** (Phase 1) + **partially** (Phase 2 in progress) | `space/`, `mission/`, CelesTrak connector (this phase) | Phase 1 uses bundled sample TLE; Phase 2 adds an optional real connector. |
| 4 | Deterministic scientific computation | **implemented** | `space/propagation.py` (SGP4), `space/geodesy.py` | No LLM on the math path (SR-01). |
| 5 | Scientific verification | **implemented** | `verification/checks.py` (9 deterministic checks) | Structured findings; never raises on bad data (SR-08). |
| 6 | Provenance & evidence | **implemented** | `governance/provenance.py`, `OrbitalSourceRecord`, sidecars | Claim-level provenance; Phase 2 extends with fetch/cache/freshness provenance. |
| 7 | Confidence & uncertainty | **partially implemented** | `governance/epistemic.py` (7-state status) | Epistemic labeling done; numeric confidence intentionally **deferred** to where a defensible scoring method exists (ADR-0006). |
| 8 | Visual intelligence | **partially implemented** | `visualization/charts.py` (altitude + ground-track) | Static charts done; interactive/maps/Cesium/D3 **deferred** (Phase 5). |
| 9 | Memory & knowledge architecture | **planned** | `memory`/`knowledge`/`retrieval` are doc-only | **Deferred** to Phase 3 (PostgreSQL/pgvector). |
| 10 | Research Autopilot | **deferred** | `ROADMAP.md` Phase 7 | Not started; reviewer-gated by design. |
| 11 | Tool Forge | **deferred** | `ROADMAP.md` Phase 6 | Generated code never executed/auto-promoted; design only. |
| 12 | Safety & approval gates | **partially implemented** | `SAFETY_REQUIREMENTS.md`, `ApprovalRecord`, audit | Hard safety rules enforced; human-approval queue modeled, enforced as risky features arrive. |
| 13 | Data-rights registry | **partially implemented** (this phase) | `sources/` policy models, `DATA_RIGHTS_AND_SOURCE_POLICY.md` | Phase 2 introduces typed source policy/license records with explicit "requires review" labeling. |
| 14 | Observability | **partially implemented** | `observability/`, structured logs, audit, `/health` | Logs + audit + health/capabilities; OpenTelemetry/metrics **deferred** (Phase 8). |
| 15 | Cost control | **partially implemented** | `OBSERVABILITY_MODEL.md` (cost = $0 now) | No paid resources; `cost_event` concept reserved. Phase 2 stays free (no paid APIs). |
| 16 | Qiskit / quantum boundary | **implemented** (bounded) | `quantum/adapter.py`, ADR-0005, `experiments/quantum/` | Simulator-only, off mission path, classical baseline required; QAOA **deferred** (Phase 4). |
| 17 | Python version policy | **implemented** | ADR-0002 | Prod baseline 3.12; dev 3.14.4 verified (cp314 wheels). |
| 18 | PostgreSQL target architecture | **planned** | ADR-0003, repositories behind interfaces | SQLite now; Postgres is a config + migration change, no domain rewrite. |
| 19 | Cloud deployment direction | **deferred** | `DEPLOYMENT_ARCHITECTURE.md`, Phase 8 | Cloud-portable design; no cloud resources; deployment requires owner approval. |
| 20 | Universal science cortex (multi-domain) | **planned / partially** | only `space` domain implemented | Architecture supports adding domains; multi-domain breadth is future work. |
| — | "Living / self-evolving" (literal) | **intentionally rejected** | ADR-0005, SAFETY_REQUIREMENTS SR-09 | Translated to human-approved, test-gated improvement; no self-deploy. |
| — | "Knows everything" (literal) | **intentionally rejected** | PRODUCT_REQUIREMENTS "What it is NOT" | Translated to explicit `unknown` status + bounded scope. |
| — | Fixed swarm of 108 agents | **intentionally rejected** | ADR-0001 | One orchestrator + dynamic domain modules. |

## Contradictions / unclear items (to confirm against the real documents)
- **C-1 (unclear):** Exact CelesTrak GP endpoint and licensing terms are not stated
  in any available document; treated as configurable + offline-fixture-tested, with
  licensing labelled "requires review" (ADR-0008, R-012).
- **C-2 (unclear):** Whether numeric confidence scoring is required for orbital
  outputs — current decision (ADR-0006) withholds confidence % from deterministic
  calculations; revisit if the documents mandate otherwise.
- **C-3 (potential contradiction):** "Cloud-first" framing vs "prefer simple infra"
  — resolved in favour of local-first now, cloud-portable design (ADR-0001/0003).

## Decisions changed by this reconciliation
**None of the accepted ADR decisions were changed.** No documents justified a
change; existing ADRs stand. New ADRs **0008–0010** are added for Phase 2 scope.
This file (and R-001) must be revisited when the authoritative documents arrive.
