# Optimization Benchmarks

Run exact + greedy + (optional) quantum on the same normalized instance, independently
verify every schedule, and produce a policy-driven conclusion + artifacts. See
ADR-0025/0028 and [QUANTUM_BENCHMARK_POLICY.md](../architecture/QUANTUM_BENCHMARK_POLICY.md).

## Run a benchmark (API)
```bash
curl -X POST localhost:8000/api/v1/optimization/problems/<problem_id>/benchmark \
  -H 'content-type: application/json' \
  -d '{"seed":7,"shots":2048,"optimizer_iterations":24,"qaoa_layers":1,
       "generate_artifacts":true,"policy_id":"strict-v1"}'
```
The comparison thresholds are **server-owned**: a request selects a policy by `policy_id`
(`strict-v1` default, or `lenient-v1`) — it does **not** send raw `competitive_relative_gap` /
`min_feasible_sample_ratio` values (those are rejected as client-supplied thresholds). The
response carries the full `run` (solver results + quantum experiment + comparison), the
`findings` (verification), `verified`, and a disclaimer. `run_quantum:false` runs the classical
baselines only.

## Evidence signing (execution receipts)
Each accepted benchmark is sealed with an HMAC-SHA256 **execution receipt** that binds the
problem/policy/association ids and every config/sample/circuit/artifact digest, plus the
worker's 128-bit execution nonce for quantum runs.

- **Key config** (env only, never the DB/logs): `ORBITMIND_EVIDENCE_SIGNING_KEY` (the active
  secret), `ORBITMIND_EVIDENCE_SIGNING_KEY_ID` (default `primary`), and
  `ORBITMIND_EVIDENCE_SIGNING_RETIRED_KEYS` (`kid1:secret1,kid2:secret2` for verify-only
  rotation). Secrets are `SecretStr` — they never appear in `repr`, `model_dump`, logs, errors,
  audits, or any API response.
- **Key strength + startup validation**: a configured key must be **≥ 32 bytes** and not a known
  placeholder (`changeme`, `placeholder`, …); active + retired key ids and material must be
  distinct. Malformed signing configuration (a retired entry without `id:secret`, a blank id or
  secret, a duplicate id/material, an active id repeated in retired, a weak/placeholder retired
  key) **fails startup** — entries are never silently skipped. Generate a key with
  `python -c "import secrets;print(secrets.token_urlsafe(48))"`.
- **Strict receipt schema**: receipt + payload models reject unknown fields (`extra="forbid"`);
  the receipt id must be a real UUID, and `issued_at` must be a non-empty, timezone-aware **UTC**
  timestamp inside a bounded acceptance window (naive/non-UTC/empty/far-future are rejected). The
  format version, signature algorithm, comparison version, and lowercase-hex signature/checksum
  are allowlisted.
- **No-signer mode**: when the key is **empty**, benchmarks run **diagnostically but are never
  ACCEPTED** (execution provenance unavailable). There is **no implicit test-environment
  signer** — tests inject a key explicitly. `.env.example` ships a **blank** key.
- **Rotation**: the active key signs; retired keys verify only. A receipt signed by a retired
  key still verifies while that key is in the keyring and degrades to an honest
  `unknown-key-id` (not a crash) once removed.
- **Receipt linkage in artifacts**: the signed receipt (public metadata + canonical payload +
  signature, never the secret) is embedded into every artifact sidecar, so a consumer can
  authenticate a sidecar **offline** (no DB) via the embedded HMAC + field binding.
- **Timeout/failure prohibition**: a quantum experiment that is not a **completed** worker run
  (timed-out/failed/cancelled/unsupported/inconclusive) receives **no receipt**, is **not
  accepted**, yields an `insufficient-evidence` conclusion, and registers **no** memory edges.
- **Malformed auxiliary evidence**: the pure conclusion policy validates every supplied numerical
  auxiliary up front; a present-but-non-finite value (NaN/inf known optimum, objective gap, etc.)
  forces `insufficient-evidence` rather than slipping into a positive branch.
- **Cleanup observability**: artifact cleanup returns an explicit, secret-free `CleanupResult`;
  a real deletion failure is logged + audited and the **original** benchmark error is re-raised
  unmasked (no `suppress`, no `ignore_errors`).

## Read-time verification (do not trust the stored flag)
Every read **re-authenticates**: it reconstructs the domain benchmark from persistence and
re-runs semantic + ownership + receipt verification — the stored `verification_passed` flag is
never trusted on its own.

- `GET /runs` returns strict, re-authenticated `RunSummaryView`s (no paths/config).
- `GET /benchmarks/<id>` returns the authenticated benchmark; a tampered row is served with
  `integrity_failed:true` and a non-positive conclusion (never a positive serve).
- `GET /runs/<id>/artifacts` returns artifacts only for **authenticated** evidence: a tampered/
  malformed benchmark is withheld with a bounded `422`, and an **unauthenticated** one
  (no signer / unaccepted / failed receipt) returns `409 evidence_not_authenticated` — diagnostic
  artifacts are never served as ordinary evidence.
- `GET /api/v1/visual-manifests/optimization-benchmark/<id>` returns a read-only visual manifest
  projection for authenticated benchmark artifact metadata. This visual manifest is a path-free,
  sidecar-free, non-authoritative API response; it is **not** the signed receipt's canonical
  artifact manifest. It delegates to the same benchmark read authentication as the artifact
  endpoint, so deleted artifact files or required authentication sidecars can make it fail closed
  with a sanitized `422`. The response never exposes receipt/signing internals, quantum internals,
  raw samples, circuits, QUBO internals, or solver internals.
- `GET /benchmarks/<id>/evidence-graph` re-authenticates, then navigates **only that benchmark's
  own** memory edges (selected by `benchmark_id` ownership, so one benchmark's tamper cannot
  affect another's edges); if re-auth fails every edge is flagged `integrity_failed` and
  `valid_evidence:false` (the edges + audit history are retained, not deleted).
- `GET /memory/graph/<id>/neighbors` (generic navigation) is **benchmark- and integrity-aware**:
  optimization edges are grouped by `benchmark_id`, each benchmark is authenticated independently,
  and every edge carries `benchmark_id` + `evidence_validity` (valid / integrity-failed /
  not-optimization). `valid_only=true` filters out integrity-failed edges; the default view keeps
  them, visibly marked, for forensic history. One benchmark's tamper never marks another's edges.

### Canonical persisted evidence (independently recomputed)
Read-time reconstruction loads the authoritative parent evidence AND verifies the persisted
`quantum_sample_results` child rows for **complete equality** against it. Every quantum sample
scalar is **independently recomputed** from the canonical problem + bitstring (selected ids, raw
mission value, weighted value, feasibility, full violation set, objective, QUBO energy, probability
from count/authoritative shots) — the recomputed evaluator result, not the persisted evaluation, is
the reference. The signed receipt's `sample_map_digest` covers the **complete** canonical sample
record (incl. raw mission value + violation count), and `worker_output_digest` binds the selected
feasible/infeasible samples, feasible-sample ratio, exact-optimum-in-samples, and objective gap.
A **coordinated** mutation of the same finite value in BOTH the parent JSON and the child row
therefore still fails, because the immutable signed receipt represents the original accepted
evidence. **Malformed** persisted JSON (solver/quantum/comparison/receipt/policy, incl. a missing
or `{}` thresholds object) is classified as `malformed-persisted-evidence` and returns a bounded
integrity response, **never an uncaught exception / HTTP 500** and never a synthesized default.
On any integrity failure an `optimization.benchmark_integrity_failed` audit is written in its own
transaction; the original data + audit history are preserved for forensic review.

### Scientific metadata is receipt-bound
The receipt's `scientific_metadata_digest` binds every material caveat + label: exact/greedy/
quantum/comparison limitations, comparison rationale, solver/quantum/comparison epistemic status,
solver/optimality status, and the final conclusion. Changing any of them after acceptance — even a
**benign** non-overclaiming replacement, or downgrading the epistemic label — invalidates read
authentication. The bounded overclaim validator additionally runs over every evidence-text field,
so `quantum advantage verified` fails in any of them.

### Strict signed artifact sidecars (online == offline)
Each sidecar carries `sidecar_format_version`, its **canonical artifact entry** (id, type,
checksum, media type, limitations, epistemic status, verification state, ownership ids, evidence/
policy anchors), the **complete canonical manifest**, and a strict receipt envelope. Authentication
verifies the receipt HMAC, requires the envelope to contain EXACTLY the expected keys (missing or
extra fails closed), cross-checks every duplicated envelope value against the signed payload,
proves the entry is a **member** of the signed manifest, recomputes the manifest digest vs the
payload, requires every duplicated top-level field to equal the canonical entry, and (given the
artifact file checksum) confirms it. **Read-time online verification invokes the SAME detached
routine offline consumers use** — a changed checksum/type/limitations/epistemic-status, a tampered
envelope, a copied sidecar, or a valid receipt paired with the wrong manifest is rejected both
ways.

### PostgreSQL ownership + solver-role enforcement
PostgreSQL rejects, with transaction recovery: a greedy result in the exact slot (or vice versa),
a tampered comparison role column, a cross-benchmark association repoint, a child row anchored to
another problem, reassigning a benchmark to a different problem, and **any solver_runs.solver_kind
outside `('exact','greedy')`** (`bogus`, `quantum-qaoa`, empty, mis-cased) — via role-aware
composite FKs (`benchmark_id, id, problem_id, solver_kind`), CHECK-pinned role columns, a
`CHECK (solver_kind IN ('exact','greedy'))`, and `(benchmark_id, problem_id)` ownership FKs to the
parent benchmark. Quantum experiments live in their own table.

## Historical policy verification
The benchmark carries an immutable, **self-validating** policy snapshot. Verification
authenticates an **active** policy against the server registry, and a **retired** policy (no
longer in the registry) against that self-consistent snapshot — so historical evidence stays
verifiable after a controlled retirement instead of crashing or silently switching thresholds.

## Trust limits
Receipts attest **execution provenance + integrity** of a bounded, simulator-only benchmark on
a tiny fixture (epistemic status `model-estimate`). They are **not** evidence of quantum
advantage, and not a verified scientific fact. A valid receipt only proves the evidence was
produced + sealed by the trusted runtime and has not been altered.

## Artifacts
With `generate_artifacts:true`, files are written under `artifacts/<run_id>/`, each with a
JSON sidecar (artifact type, problem checksum, solver, timestamp, software versions, seed,
epistemic status `model-estimate`, verification summary, checksum, limitations):
1. `selected_timeline.png` — selected-observation timeline
2. `objective_comparison.png` — solver objective comparison
3. `feasibility_comparison.png` — feasibility / constraint-violation comparison
4. `quantum_sample_distribution.png` — sample counts coloured by feasibility
5. `circuit_diagram.png` (or `.txt` fallback) — the QAOA circuit (documentation only)
6. `benchmark_summary.json` — machine-readable summary

Retrieve metadata: `GET /api/v1/optimization/runs/<run_id>/artifacts`. **Generated
artifacts/images are git-ignored and never committed.**

## Verification gate
A benchmark is only registered to scientific memory if **all critical/error checks pass**
(`opt.qubo_energy_equivalence`, `opt.same_instance`, `opt.quantum_simulator_only`,
`opt.quantum_sample_observed`, `opt.conclusion_policy`, objective recomputation, …). A
solver result failing verification is **not** marked successful.

## Memory integration (bounded)
On a verified benchmark, bounded entity links are registered (NO broad claims): problem
`solved-by` solver run, solver run `produced` schedule, quantum experiment
`compared-against` exact run, comparison `supported-by` artifacts. Query with
`GET /api/v1/memory/graph/<problem_id>/neighbors`.

## Local PostgreSQL benchmark validation
The Phase 4A tables migrate cleanly to head on PostgreSQL; run the PostgreSQL-marked
suite (see [POSTGRESQL_LOCAL_OPERATIONS.md](POSTGRESQL_LOCAL_OPERATIONS.md)):
```bash
ORBITMIND_TEST_POSTGRES_URL=postgresql+psycopg://orbitmind:orbitmind@127.0.0.1:55432/orbitmind_test \
  python -m pytest -m postgres tests/integration/test_postgres_optimization.py -v
```
