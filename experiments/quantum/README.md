# Quantum Experiments (isolated)

This directory is **deliberately separated from production mission logic**
(ADR-0005). Nothing here is imported by `orbitmind.api` or the orbital mission
pipeline, and none of it runs on an API request.

- `bell_state.py` — a Qiskit Aer **simulator** Bell-state smoke experiment with a
  classical expectation comparison. Simulator-only; never contacts real hardware.

Run manually:

```bash
.venv\Scripts\python experiments\quantum\bell_state.py
```

Quantum optimization (QAOA / QUBO) is intentionally **not** here yet. It arrives in
Phase 4 with a mandatory classical baseline and a reproducible objective +
wall-clock comparison. No "quantum advantage" is claimed without that evidence.
