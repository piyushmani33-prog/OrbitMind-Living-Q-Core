# Reference Reconciliation — OrbitMind Living Q-Core

Status: **Active — reconciled against the actual reference documents** (inspected
and hashed 2026-06-19; see `../reference/REFERENCE_MANIFEST.md`). This supersedes the
earlier prompt-only provisional reconciliation.

Source documents (abbreviations used below):
- **Vision** = `OrbitMind Living Q-Core.docx` (SHA-256 `743df0…7060`)
- **Brief** = `OrbitMind Living Q-Core Feasibility Brief.docx` (SHA-256 `aa56ed…bf26`)

Status legend: `implemented · partially implemented · planned · deferred ·
intentionally rejected · contradicted · unclear`.

## Aspirational-language translation
Both documents **themselves** reject literal omniscience/autonomy and reframe it as
bounded engineering; this reconciliation does the same.

| Aspirational phrase (source) | Bounded, testable capability |
|---|---|
| "living / self-evolving" (Vision/Brief) | Lab-bound improvement with benchmark comparison + **human approval**; no self-deploy (SR-09). |
| "knows everything / universal science cortex" (Brief) | Continuously updated, **source-grounded, simulation-capable, benchmarked** retrieval+reasoning; explicit `unknown` when out of scope. |
| "quantum intelligence as its main brain" (Brief) | Bounded, simulator-first Qiskit **optimizer**, off the mission path, classical baseline required (ADR-0005). |
| "108 brains / swarm" (Brief) | One Prime Orchestrator + dynamically invoked domain workers (ADR-0001). |

## Traceability matrix (28 items)
Each item: **Source** (doc · section) · **Interpretation** · **Implementation** ·
**Gap** · **Target phase** · **Status**.

1. **Product mission** — *Vision §Executive summary; Brief §"most important real-world shift".* Interpretation: a cloud-first scientific intelligence system for Earth/orbital/research workflows with guarded tool generation + optional quantum optimization; not a "god-brain". Impl: `PRODUCT_REQUIREMENTS.md`, Phase 1 orbital slice, Phase 2 connector. Gap: broader domains + memory. Target: Phase 3+. **Status: partially implemented.**

2. **Permanent system spine** — *Brief §"A practical request flow"; Vision §"system spine … permanent invariant" (diagram).* Interpretation: mission → orchestrator → domain workflow → data/tool → verifier → memory update → visual/report → approval/deploy gate. Impl: `orchestration/orchestrator.py`, `MISSION_LIFECYCLE.md` — full traversal. Gap: memory-update node = persistence/audit only; approval node is a policy no-op for read-only compute. Target: memory Phase 3, approvals Phase 6/7. **Status: implemented** (memory/approval nodes partially).

3. **Modular-monolith strategy** — *Brief §"What the product should actually be" (five coupled planes "instead of one giant monolith"); Vision §"five bounded planes".* Interpretation: strong logical separation into planes; reject the 108-agent swarm. Impl: modular monolith with enforced boundaries mapping to planes (ADR-0001), extraction seams for high-load/execution zones. Gap: execution-zone (Tool Forge sandbox) extraction. Target: Phase 6/8. **Status: implemented.** *Note: "instead of one giant monolith" = a **modular** monolith; alignment, not contradiction.*

4. **Satellite intelligence** — *Vision §Data sources & Visual Intelligence; Brief §"What to build first".* Impl: Phase 1 SGP4 propagation + WGS-84 geodesy + verification; Phase 2 CelesTrak connector. Gap: visible-satellite/orbit-view endpoints, more connectors, Cesium orbit view. Target: Phase 2+/5. **Status: partially implemented.**

5. **Deterministic scientific computation** — *Brief §"scientific computation" (NumPy/SciPy/SymPy/xarray; Astropy/sgp4/Skyfield).* Interpretation: LLM plans, deterministic engines compute. Impl: deterministic SGP4 + geodesy (SR-01: no LLM on math path). Gap: SymPy/SciPy/xarray/Astropy general compute. Target: Phase 3+. **Status: partially implemented.**

6. **Scientific verification** — *Brief §"Correctness must be engineered in layers".* Impl: `verification/checks.py` (9 deterministic checks), typed boundaries, pytest/mypy/ruff gates. Gap: scientific claim verification beyond orbital sanity. Target: Phase 3/7. **Status: partially implemented.**

7. **Provenance and evidence** — *Vision/Brief: "source provenance preserved at every step".* Impl: `ProvenanceRecord`+`EvidenceReference`, source policy/fetch/cache records, artifact sidecars, `MissionSourceData`. Gap: claim-level provenance into a knowledge graph. Target: Phase 3. **Status: implemented** (mission-level); claim-level **planned**.

8. **Epistemic status** — *Brief §"structured outputs with confidence, freshness, uncertainty"; Vision §"nothing moves from generation to truth".* Impl: `EpistemicStatus` enum (ADR-0006); SGP4 = deterministic-calculation; generated text never `verified-fact`. Gap: none for current scope. Target: extend Phase 3/7. **Status: implemented.**

9. **Confidence and uncertainty** — *Brief §Executive assessment ("confidence scoring, data freshness checks").* Impl: freshness states + epistemic labels; confidence % deliberately **withheld** from deterministic calc (ADR-0006). Gap: defensible confidence scoring for model/hypothesis outputs. Target: Phase 3/7. **Status: partially implemented.**

10. **Source rights and licensing** — *Brief §"formal per-source rights registry from the beginning"; §"data-rights heterogeneity".* Impl: typed `SourcePolicy`+`SourceLicenseRecord` (Phase 2), `DATA_RIGHTS_AND_SOURCE_POLICY.md`; CelesTrak rights = `requires_review`. Gap: more sources; legal confirmation (R-012b, R-015). Target: Phase 2+. **Status: implemented** (framework); coverage **partial**.

11. **Memory and knowledge graph** — *Vision §"Knowledge, retrieval, reasoning" (documents/chunks/concepts/senses/claims/evidence/graph_edges; pgvector hybrid retrieval; LaBSE WSD).* Impl: none yet (mission persistence + audit only). Gap: the entire knowledge plane. Target: **Phase 3.** **Status: planned.**

12. **Visual intelligence** — *Vision/Brief §"Visual Intelligence/organ" (Plotly/Leaflet/D3/CesiumJS, native).* Impl: Matplotlib altitude + ground-track artifacts + JSON sidecars. Gap: interactive Plotly, maps, Cesium orbit view, D3 graph, dashboards. Target: **Phase 5.** **Status: partially implemented.**

13. **Research Autopilot** — *Vision §"Research Autopilot" (hypothesis lifecycle idea→candidate→simulated→benchmarked→reviewer-approved→verified/rejected).* Impl: none (roadmap + safety rules). Gap: whole capability. Target: **Phase 7.** **Status: deferred.**

14. **Tool Forge** — *Vision/Brief §"Tool Forge" (lab→quarantine→live; gVisor/Firecracker; never self-promote).* Impl: none; design + SR-09. Gap: whole capability + sandbox. Target: **Phase 6.** **Status: deferred** (design only).

15. **Approval gates** — *Brief §"manual approval before anything generated moves from lab to live".* Impl: `ApprovalRecord` modeled; spine approval node (no-op for read-only); SR-18. Gap: approval queue + enforcement for risky actions. Target: Phase 6/7. **Status: partially implemented** (modeled).

16. **Observability** — *Brief §"For observability… OpenTelemetry, Prometheus, Grafana"; living dashboard shows queue depth/latency/freshness/cost.* Impl: structured logs + append-only audit + `/health` + `/system/capabilities` + WorkflowRun step log. Gap: OTel traces/metrics, dashboards, alerts. Target: **Phase 8.** **Status: partially implemented.**

17. **Cost control** — *Vision §"cost brain" (≈USD 1.5–4.5k/mo; focus cache hit rate, retries, token budgets).* Impl: cost = $0 (no paid resources); cache-first reduces fetches; `cost_event` concept reserved. Gap: cost telemetry/budgets/alerts. Target: **Phase 8.** **Status: planned** (partial via caching).

18. **Disaster recovery** — *Vision §"PostgreSQL continuous archiving and PITR".* Impl: git rollback; missions reproducible-from-inputs; `RUNBOOK.md` SQLite backup/restore + Alembic downgrade. Gap: Postgres PITR, object-storage versioning, DR rehearsals. Target: **Phase 8.** **Status: planned.**

19. **Qiskit & quantum boundaries** — *Vision/Brief §"Quantum Organ" (Sampler/Estimator, QAOA; simulator first, classical fallback; "prove value without quantum advantage"; qiskit-optimization no longer IBM-supported).* Impl: bounded adapter (ADR-0005), simulator self-test, off mission path, Bell experiment; QAOA/QUBO deferred. Gap: benchmarked QUBO/QAOA vs classical baseline. Target: **Phase 4.** **Status: implemented** (bounded adapter); optimization **deferred**. New risk **R-018**.

20. **Python version policy** — *Brief/Vision §"Python 3.12 production baseline; 3.14 needs lockfile validation".* Impl: ADR-0002 (3.12 baseline; dev on 3.14.4, wheels verified). Gap: none. Target: ongoing. **Status: implemented** (confirmed by references).

21. **PostgreSQL target** — *Vision/Brief §"PostgreSQL authoritative system of record + pgvector".* Impl: SQLite now via SQLAlchemy + repository interfaces; ADR-0003 documents Postgres target. Gap: actual Postgres + pgvector. Target: **Phase 3/8.** **Status: planned** (interfaces ready).

22. **Cloud-first direction** — *Vision/Brief §"cloud-first; Azure Container Apps; Linux containers from day one".* Impl: Dockerfile + compose (containerized); local-first development; cloud deferred. Gap: managed cloud deployment. Target: **Phase 8.** **Status: partially implemented / deferred** — sequencing divergence **recorded in ADR-0011** (not a rejection).

23. **Universal science cortex** — *Brief §"becomes real only via retrieval/simulation/verification, not 'know everything'".* Interpretation (translated): bounded, source-grounded, simulation-capable, benchmarked multi-domain retrieval+reasoning, reviewer-gated. Impl: single (space) domain + provenance/verification foundation. Gap: multi-domain breadth + knowledge plane. Target: Phase 3+. **Status: planned** (literal omniscience **intentionally rejected**, per the documents themselves).

24. **Earth science** — *Brief §"xarray for labeled multidimensional Earth-science; NASA Earthdata".* Impl: none (orbital only). Gap: Earthdata connector + xarray gridded data. Target: Phase 2+/3. **Status: planned.**

25. **Planetary science** — *Vision/Brief §"Astropy general astronomy backbone; Skyfield/sgp4".* Impl: sgp4 Earth-orbit propagation (a subset). Gap: planetary ephemerides, Astropy/Skyfield frames. Target: Phase 3+. **Status: partially implemented** (orbital subset only).

26. **Astrobiology** — *Not named in either document.* Closest: Brief §"chemistry and biology expansion … RDKit, Biopython, ASE … within bounded domains … not an unsupervised wet-lab scientist." Interpretation: bounded *computational* biology only, reviewer-gated, far future; **no wet-lab**. Impl: none. Gap: entire domain. Target: far future (beyond current roadmap). **Status: unclear** (not explicitly in references) → subsumed under the bounded chemistry/biology extension; **deferred**.

27. **Astrochemistry** — *Not named in either document.* Closest: Brief §"chemistry … RDKit". Interpretation: bounded *computational* chemistry only; no real-world experimentation. Impl: none. Gap: entire domain. Target: far future. **Status: unclear** (not explicitly in references); **deferred**.

28. **Autonomous research limitations** — *Brief §"self-evolution as lab-bound improvement … human approval"; "generated tools never self-promote"; Vision §"Nothing should move directly from generation to truth".* Impl: SR-09 (untrusted generated code, no self-deploy), SR-04 (no generated text as verified fact), epistemic labeling, `ApprovalRecord`. Gap: enforcement lands with Tool Forge/Research Autopilot. Target: Phase 6/7. **Status: implemented** (as binding safety policy); enforcement for future features **partial**. Literal autonomy **intentionally rejected**.

## Contradictions / divergences
- **No hard contradiction** of any accepted decision was found. The references
  **confirm** the modular-monolith, Python 3.12, Postgres target, bounded quantum,
  Tool Forge lifecycle, data-rights registry, and "no unverified claim as fact".
- **One sequencing divergence:** references are "cloud-first"; the build is
  "local-first now, cloud-portable, cloud in Phase 8". Recorded, not silently
  changed → **ADR-0011**.
- **One justified technical correction:** CelesTrak min polling interval was 3600s;
  the references' official guidance is 2 hours → floored at **7200s**
  (`CELESTRAK_VERIFICATION.md`, ADR-0008).

## Changes applied by this reconciliation
- Code: CelesTrak `min_refresh_seconds` floored at the official 7200s (+ test).
- ADRs: **ADR-0011** added (deployment posture); ADR-0002 + ADR-0008 annotated with
  reference-confirmation notes (decisions unchanged).
- Risk: **R-001 closed** (documents inspected/hashed); **R-012 split** into R-012a
  (technical, closed/mitigated) and R-012b (legal rights, open); **R-015..R-018**
  added.
- Docs: this file, `REFERENCE_MANIFEST.md`, `CELESTRAK_VERIFICATION.md`, derivatives.

## Phase 3A update (2026-06-20)
Phase 3A (unified space-object model + JPL small-body intelligence; ADR-0012..0017)
advances several matrix items without contradicting any accepted decision:
- **Satellite/space intelligence (#4)** → broadened from satellites to **natural small
  bodies** (asteroids/comets) via official JPL APIs; status remains *partially
  implemented* (more object classes + Horizons deferred).
- **Planetary science (#25)** → still *partially implemented*; small bodies are now
  covered, but planetary/lunar ephemerides remain planned.
- **Deterministic scientific computation (#5)** and **scientific verification (#6)** →
  extended with small-body normalization + a dedicated deterministic check suite.
- **Source rights & licensing (#10)** → a second real source family (JPL) added under the
  same typed policy/rights framework (`requires_review`); new risk **R-019**.
- **Universal science cortex (#23)** → the kind-agnostic `SpaceObject` model is the
  multi-domain foundation the references call for (still *planned* overall).
- **Memory & knowledge graph (#11) / PostgreSQL (#21)** → unchanged (*planned*),
  explicitly re-sequenced to **Phase 3B** (ADR-0012); the new object model is the entity
  shape a future knowledge graph will index.
The reconciliation matrix above remains valid; these are advances in status, not
reversals.

## Items requiring NO change (already aligned)
ADR-0001 (modular monolith), ADR-0003 (Postgres target via interfaces), ADR-0004
(Temporal deferred behind an interface), ADR-0005 (bounded quantum), ADR-0006
(epistemic status), ADR-0007 (orbital slice). The references validate all of these.
