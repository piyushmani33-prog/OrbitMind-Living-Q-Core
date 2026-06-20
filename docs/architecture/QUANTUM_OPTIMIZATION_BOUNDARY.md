# Quantum Optimization Boundary (Phase 4A)

The quantum layer is a **bounded, simulator-only, experimental adapter** — NOT OrbitMind's
cognition engine. OrbitMind's intelligence is the deterministic spine (intake →
orchestration → domain tools → verification → evidence/memory). The quantum adapter runs
one tiny experiment (satellite observation scheduling) and is recorded, verified, and
compared against mandatory classical baselines. See ADR-0005, ADR-0024–0029.

## Hard boundaries
- **Simulator only** (Qiskit Aer). No real hardware, no IBM account, no API key, **no
  network** (ADR-0027).
- **Mandatory classical baselines** on the same normalized instance (ADR-0025).
- **Every schedule independently re-verified** by the shared deterministic evaluator; a
  solver's own claim is never trusted (ADR-0028).
- **No quantum-advantage overclaim.** `quantum-competitive` means a defined bounded
  threshold was met for one tiny instance, nothing more.
- **No production control.** An experimental quantum result never drives a mission.
- **Bounded** size/shots/iterations/timeout (ADR-0029).

## Why simulator results do not demonstrate hardware advantage
A noiseless (or simply-noised) simulator on a 3–4 qubit problem says nothing about real
quantum hardware: no decoherence, no gate-error budget, no connectivity limits, no
queueing, and no scaling evidence. Matching the classical optimum on a tiny instance is a
correctness check of the encoding and the QAOA, not a performance claim.

## Module map (`src/orbitmind/optimization/`)
| File | Responsibility |
|------|----------------|
| `models.py` | Typed domain models + status/conclusion enums. |
| `problem.py` | Normalization, deterministic checksum, conflict generation, penalty sizing. |
| `evaluation.py` | The shared deterministic evaluator (the independent verifier). |
| `qubo.py` | Manual QUBO + Ising conversion + energy (ADR-0026). |
| `solvers/` | Exact (exhaustive ground truth) + greedy (deterministic heuristic). |
| `quantum.py` | Aer QAOA circuit, sampling, decoding, sample diagnostics. |
| `benchmark.py` | Fair benchmark orchestration + comparison-conclusion policy. |
| `verification.py` | Deterministic checks (QUBO equivalence, simulator-only, same-instance, …). |
| `fixtures.py` | Bundled tiny deterministic instances. |
| `service.py` | Session + audit + persistence + artifacts + bounded memory links. |

Related: [SATELLITE_OBSERVATION_SCHEDULING.md](SATELLITE_OBSERVATION_SCHEDULING.md),
[QUBO_ENCODING.md](QUBO_ENCODING.md), [QUANTUM_BENCHMARK_POLICY.md](QUANTUM_BENCHMARK_POLICY.md).
