"""Bounded classical-vs-quantum satellite observation scheduling (Phase 4A).

A deliberately small, scientifically honest experiment: choose a set of observation
opportunities that maximizes mission value subject to conflicts and resource limits,
and compare deterministic classical baselines against a simulator-only QAOA experiment
on the *same normalized problem instance*.

Hard rules (ADR-0005, ADR-0024..0029):
- Quantum is **simulator-only** (Aer), off the production mission path, with a
  **mandatory classical baseline** for every experiment.
- Every returned schedule (classical OR quantum) is independently re-verified by a
  shared deterministic evaluator; a solver's own feasibility claim is never trusted.
- **Never claim general quantum advantage.** ``quantum-competitive`` means only that a
  bounded instance met a defined threshold.
- No real hardware, no IBM account, no network, fixed seeds, bounded size/iterations.
"""
