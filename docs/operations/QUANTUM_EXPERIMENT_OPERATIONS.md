# Quantum Experiment Operations

The quantum experiment is **simulator-only** (Aer), offline, and bounded. See ADR-0027/0029.

## Prerequisites
Qiskit + Aer come from the optional `[quantum]` extra:
```bash
pip install -e .[quantum]      # qiskit, qiskit-aer (already present in dev)
```
Installed/validated versions: **Qiskit 2.4.2, qiskit-aer 0.17.2**. If Aer is absent,
quantum endpoints return a clear `unsupported` status (never a silent fallback).

## Run a standalone experiment (API)
```bash
curl -X POST localhost:8000/api/v1/optimization/problems \
  -H 'content-type: application/json' -d '{"fixture":"default"}'
# -> {"id": "<problem_id>", ...}

curl -X POST localhost:8000/api/v1/optimization/problems/<problem_id>/solve/quantum \
  -H 'content-type: application/json' \
  -d '{"seed":7,"shots":2048,"optimizer_iterations":24,"qaoa_layers":1,"timeout_seconds":30}'
```
The response is a `QuantumExperiment` with circuit metadata (qubits, depth, gate counts,
seeds), all samples (feasible + infeasible), the best verified feasible sample, the
feasible-sample ratio, and the objective gap vs the exact optimum.

## Configuration & reproducibility
- Fixed `seed` drives `seed_simulator` and `seed_transpiler` (both recorded).
- Parameters are chosen by a deterministic grid (p=1) / seeded search (p>1) — recorded as
  `optimizer_iterations` + `best_parameters`.
- **No network, no IBM account, no API key, no real hardware.** All sampling is local Aer.
- Reproducibility limits: shot noise + the grid resolution. Re-running with the same seed +
  package versions on the same machine reproduces the samples.

## Safety
- An experimental quantum result **never** drives a production mission.
- The API rejects unsupported solver/backend names, out-of-range shots/iterations/timeout,
  arbitrary Python, and raw Qiskit object input (structured JSON only) — ADR-0029.
- Circuit diagrams are documentation of what ran; they are **not** evidence of quantum
  performance.
