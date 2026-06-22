# Quantum Benchmark Policy (Phase 4A)

See ADR-0028. The benchmark is fair, fully recorded, and conservatively labelled. **It
never claims general quantum advantage.**

## Fairness
Classical (exact + greedy) and quantum solvers run the **same normalized instance**
(checksum equality is verified). For every solver we record: problem checksum, solver
name/version, configuration, seed, start/end timestamps, runtime, objective, raw mission
value, feasibility, violations, optimality status, known optimum, objective gap, resource
usage, and error/timeout status. Quantum additionally records qubits, depth, gate counts,
shots, optimizer iterations, backend, transpile level, and feasible-sample ratio. **We do
not compare objectives while hiding runtime, infeasibility, or problem size.**

## Honest sample processing
The most frequent bitstring is **not** assumed best. Each sample is decoded → independently
evaluated → raw value / violations / objective computed → the **best verified feasible**
sample is selected. Reported: total shots, distinct samples, feasible-sample ratio, best
feasible sample, best infeasible sample, objective gap vs the exact optimum, selected
sample probability, and whether the exact optimum appeared in samples. **Infeasible and
failed samples are preserved for diagnostics, never suppressed.**

## Conclusions (policy-driven, `benchmark.conclude`)
| Conclusion | Meaning |
|-----------|---------|
| `classical-exact-best` | Exact optimum found; no quantum comparison (or quantum not run). |
| `classical-greedy-best` | Greedy is the best classical; no proven optimum / no quantum. |
| `quantum-competitive` | Feasible quantum met the bounded threshold (rel-gap ≤ threshold of the proven optimum, or beat the heuristic when the optimum is unproven). **NOT advantage.** |
| `quantum-worse` | Feasible quantum below the reference beyond the threshold. |
| `quantum-infeasible` | No feasible quantum sample observed. |
| `equivalent-objective` | Quantum exactly ties the best classical when the optimum is **not** proven. |
| `insufficient-evidence` | Feasible-sample ratio below threshold, timed out with no feasible sample, or no classical reference. |
| `experiment-failed` | The quantum experiment errored. |

The verifier re-derives the conclusion from the recorded results and **rejects a mismatch**
(`opt.conclusion_policy`).

## Reproducibility & its limits
Fixed `seed`/`seed_simulator`/`seed_transpiler` and a deterministic parameter search make
a run reproducible bit-for-bit on the same machine + package versions. **Limits:** shot
noise (finite sampling), optimizer variability across parameter grids, and the fact that
matching the optimum on a 3–4 qubit simulator instance is a correctness signal, not a
performance claim. **No production decision is ever made on quantum output alone.**

## Status guards precede objective comparison (review finding #19)
The conclusion is decided by checking the quantum **status first**. A run that is
`timed-out`, `cancelled`, `failed`, `unsupported`, `pending`, `running`, `inconclusive`,
that lacks a feasible sample, or whose `problem_checksum` differs from the classical
baselines can **never** receive `quantum-competitive`/`equivalent-objective` — it is forced
to a non-positive conclusion (`insufficient-evidence` / `experiment-failed` /
`quantum-infeasible`) before any objective is compared.

## Whole-experiment timeout (review finding #3)
The quantum experiment runs in an **isolated child process** with a hard, parent-side
wall-clock deadline covering the entire operation (QUBO prep, circuit build, transpilation,
parameter search, sampling, decoding, selection). On expiry the worker is **terminated**:
no final sampling completes, the status is `timed-out`, no best solution is presented as
completed evidence, and the benchmark conclusion is non-positive.

## Tamper-resistant verification (review finding #2; second review #1/#2/#5)
The verifier **recomputes** authoritative values from canonical inputs — it re-solves the
exact/greedy baselines, re-derives the penalty + QUBO energy (exhaustively on tiny instances),
recomputes per-sample probability/feasibility/energy and the feasible-sample ratio from the
observed counts, confirms the selected sample was actually observed, recomputes artifact
checksums from disk and validates sidecar metadata, and re-derives the conclusion. A persisted
value is never trusted as proof of itself; any failed material check downgrades the run to
non-positive and blocks scientific-memory registration.

The second review hardened this further:
- **Authoritative evidence manifest** (`evidence.py`): the verifier rebuilds a server-derived
  manifest (problem + QUBO checksums, variable/qubit mapping, bit-order, encoded/unencoded
  inventory, penalty value + proof status, backend, seeds, package versions) with a
  deterministic checksum and authenticates the persisted evidence against it — a coordinated,
  internally-consistent forgery is rejected because the authoritative fields come from the
  trusted problem, not the persisted block.
- **Sample validation**: the authoritative shot count comes from the server configuration (so
  doubling counts *and* `total_shots` together is rejected), counts must be positive integers,
  bitstrings unique + correct width, and metadata shots must equal the configured shots.
- **Classical baseline authentication**: exactly one exact + one greedy (no duplicates / reused
  ids / extra kinds), exact completed + proven-optimal with a `2^n` exhaustive candidate count,
  greedy completed + matching a deterministic rerun.
- **Server-owned policy** (`policy.py`): thresholds come from an immutable registry; the verifier
  reconstructs the expected policy by id and re-derives the conclusion with the SERVER thresholds,
  so coherently changing both a persisted threshold and the conclusion fails.
- **Artifact + sidecar containment**: the expected sidecar path is derived from the artifact
  record (not trusted from it); both paths are checked with `ensure_within`, sidecar semantics are
  compared independently, and misleading quantum-advantage language is rejected.
- **Release gate** `benchmark_verified_for_evidence`: true only when every CRITICAL/ERROR check
  passes; when false the conclusion is non-positive, the benchmark is persisted unaccepted, and no
  scientific-memory edges are created.

**Remaining limit:** the verifier does not re-execute Aer, so a forgery that *coherently* rewrites
the configuration seed, the evidence seeds, and the circuit-metadata seeds together is not
re-derived from fresh sampling (the samples are still independently re-decoded + re-evaluated).
Re-running the sampler inside verification is out of scope for Phase 4A.

## Execution-origin authentication (third review)
Semantic verification (above) proves a benchmark is mathematically self-consistent; it does
**not** prove the recorded samples came from an OrbitMind-controlled execution. A signed
**benchmark execution receipt** (`optimization/receipts.py`) closes that gap.

- **Trust boundary.** *Trusted:* the running OrbitMind process, its isolated quantum worker,
  the signing component, the signing key (supplied OUTSIDE the database, via env), and the
  reviewed code + policy registry. *Not trusted as evidence by itself:* persisted rows, API
  data, artifact JSON, sidecars, mutable storage, imported records. *Not protected against:*
  an attacker controlling the runtime, possessing the key, or replacing both code and signing
  infrastructure.
- **What it proves.** HMAC-SHA256 over a canonical payload (benchmark/problem ids + checksums,
  policy snapshot checksum, association ids, config checksums, evidence-manifest checksum,
  sample-map / parameter / circuit / software / artifact digests, worker nonce + output
  digest). It proves a trusted runtime holding the secret issued the receipt **and** that the
  persisted run still matches what was signed. It does **NOT** prove Qiskit/Aer is correct or
  that any quantum advantage exists. The secret is never persisted, logged, returned, or
  committed.
- **Release gate.** Accepted quantum evidence requires a configured signer. With no signer the
  computation runs diagnostically but stays **unaccepted** (provenance unavailable): a
  non-positive conclusion, no scientific-memory edges, and the response reports it. A failed
  receipt (changed payload/signature, unknown key, wrong benchmark/problem/policy/association,
  reuse, wrong worker/artifact digest) blocks acceptance.
- **Key rotation.** A signer key id is recorded; retired keys remain in the verification
  keyring so historical receipts verify after a controlled rotation.

## Cross-benchmark ownership + policy snapshot (third review)
Every result carries server-set ownership anchors (benchmark id + internal problem id) and the
comparison's association ids are bound to same-benchmark rows by composite database FKs
(`uq_solver_runs_owner`, `fk_comparison_*_owner`). The verifier rejects cross-benchmark
splicing, a different problem id under an identical checksum, nonexistent ids, and wrong solver
kinds. The requested policy is anchored as a self-validating snapshot on `benchmark_runs`
(not only the comparison); the comparison must match the parent anchor, so a coherent
comparison-only `strict-v1`→`lenient-v1` swap fails. A persisted snapshot verifies against its
own checksum, so an old benchmark stays verifiable after a registry retirement.

## Sidecar authentication + failure audits (third review)
Quantum sidecars are authenticated field-by-field against the rebuilt evidence manifest and the
trusted run's ownership/policy anchors (not merely required to exist); a bounded overclaim
validator rejects affirmative misleading claims while permitting explicit disclaimers. Artifacts
are generated in a staging directory and atomically promoted on success; any failure removes the
staging/final directories (no orphans) and records a durable, secret-free failure audit in a
separate transaction.

## Observed bounded results (default fixtures, seed 7)
- `default` → `quantum-competitive` (matched optimum 10; feasible-sample ratio 1.0).
- `resource-bound` → `quantum-competitive` (matched optimum 15; feasible-sample ratio
  ~0.36 — resource constraints not in the QUBO).
- `mutual-exclusion` → `quantum-worse` (quantum 9 vs optimum 10) — an honest "worse"
  outcome.
