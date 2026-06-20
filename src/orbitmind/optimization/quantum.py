"""Simulator-only QAOA experiment for bounded scheduling (Aer; no real hardware).

A small, manually-built QAOA circuit minimizes the QUBO energy; parameters are chosen by
a deterministic, bounded grid/seeded search. Every sampled bitstring is independently
re-evaluated by the shared Evaluator — the most frequent sample is NOT assumed best. The
result records full circuit metadata, seeds, and feasible/infeasible sample diagnostics.

Bit-order convention: Aer returns measurement strings with qubit 0 as the RIGHTMOST
character; we reverse to the canonical variable order (index 0 first) before decoding.
"""

from __future__ import annotations

import time
from typing import Any

from orbitmind.optimization.evaluation import Evaluator
from orbitmind.optimization.models import (
    ExperimentStatus,
    QuantumCircuitMetadata,
    QuantumExperiment,
    QuantumSampleResult,
    SchedulingProblem,
    SolverConfiguration,
)
from orbitmind.optimization.qubo import build_qubo, qubo_energy, qubo_to_ising
from orbitmind.quantum.adapter import quantum_available


def _software_versions() -> dict[str, str]:
    from importlib.metadata import PackageNotFoundError, version

    out: dict[str, str] = {}
    for pkg in ("qiskit", "qiskit-aer"):
        try:
            out[pkg] = version(pkg)
        except PackageNotFoundError:  # pragma: no cover - only when uninstalled
            out[pkg] = "unavailable"
    return out


def _candidate_params(layers: int, iterations: int, seed: int) -> list[list[float]]:
    """Deterministic parameter candidates (length 2*layers): grid for p=1, seeded else."""
    import numpy as np

    if layers == 1:
        side = max(2, round(iterations**0.5))
        gammas = np.linspace(0.0, np.pi, side)
        betas = np.linspace(0.0, np.pi / 2.0, side)
        return [[float(g), float(b)] for g in gammas for b in betas][:iterations]
    rng = np.random.RandomState(seed)
    candidates: list[list[float]] = []
    for _ in range(iterations):
        vec = [float(rng.uniform(0.0, np.pi)) for _ in range(layers)]
        vec += [float(rng.uniform(0.0, np.pi / 2.0)) for _ in range(layers)]
        candidates.append(vec)
    return candidates


def run_quantum_experiment(
    problem: SchedulingProblem,
    config: SolverConfiguration,
    evaluator: Evaluator | None = None,
    *,
    known_optimum: float | None = None,
    optimum_selection: tuple[str, ...] | None = None,
) -> QuantumExperiment:
    """Run a bounded Aer QAOA experiment; returns a fully-diagnosed experiment record."""
    evaluator = evaluator or Evaluator(problem)
    base = QuantumExperiment(
        problem_checksum=problem.checksum,
        status=ExperimentStatus.PENDING,
        configuration=config,
        seed=config.seed,
        software_versions=_software_versions(),
    )
    if not quantum_available():
        return base.model_copy(
            update={"status": ExperimentStatus.UNSUPPORTED, "error": "Aer/Qiskit not installed"}
        )
    try:
        return _run(problem, config, evaluator, base, known_optimum, optimum_selection)
    except Exception as exc:  # pragma: no cover - defensive; surfaced as FAILED status
        return base.model_copy(
            update={"status": ExperimentStatus.FAILED, "error": f"{type(exc).__name__}: {exc}"}
        )


def build_qaoa_circuit(problem: SchedulingProblem, layers: int) -> tuple[Any, Any, Any]:
    """Build the (unbound) parameterized QAOA circuit + its ParameterVectors.

    Cost layer: RZ(2*gamma*h_i) + RZZ(2*gamma*J_ij); mixer: RX(2*beta). Used by the
    experiment run and the circuit-diagram artifact.
    """
    from qiskit import QuantumCircuit
    from qiskit.circuit import ParameterVector

    qubo = build_qubo(problem)
    n = qubo.num_vars
    h, j_coeffs, _ = qubo_to_ising(qubo)
    gammas = ParameterVector("g", layers)
    betas = ParameterVector("b", layers)
    qc = QuantumCircuit(n)
    qc.h(range(n))
    for layer in range(layers):
        for i, hi in h.items():
            qc.rz(2.0 * gammas[layer] * hi, i)
        for (i, k), jik in j_coeffs.items():
            qc.rzz(2.0 * gammas[layer] * jik, i, k)
        for i in range(n):
            qc.rx(2.0 * betas[layer], i)
    qc.measure_all()
    return qc, gammas, betas


def _run(
    problem: SchedulingProblem,
    config: SolverConfiguration,
    evaluator: Evaluator,
    base: QuantumExperiment,
    known_optimum: float | None,
    optimum_selection: tuple[str, ...] | None,
) -> QuantumExperiment:
    from qiskit import transpile
    from qiskit_aer import AerSimulator
    from qiskit_aer.primitives import SamplerV2

    qubo = build_qubo(problem)
    n = qubo.num_vars
    shots = min(config.shots, problem.limits.max_shots)
    iterations = min(config.optimizer_iterations, problem.limits.max_optimizer_iterations)
    p = config.qaoa_layers
    qc, gammas, betas = build_qaoa_circuit(problem, p)

    backend = AerSimulator()
    tqc = transpile(
        qc, backend, optimization_level=config.transpile_level, seed_transpiler=config.seed
    )
    sampler = SamplerV2(seed=config.seed)

    def expected_energy(values: list[float]) -> float:
        bound = tqc.assign_parameters(
            {
                **{gammas[i]: values[i] for i in range(p)},
                **{betas[i]: values[p + i] for i in range(p)},
            }
        )
        counts = (
            sampler.run([(bound,)], shots=max(128, shots // 4)).result()[0].data.meas.get_counts()
        )
        total = sum(counts.values())
        return float(sum(c * qubo_energy(qubo, k[::-1]) for k, c in counts.items()) / total)

    start = time.perf_counter()
    deadline = start + config.timeout_seconds
    candidates = _candidate_params(p, iterations, config.seed)
    best_params = candidates[0]
    best_energy = float("inf")
    evaluated_iters = 0
    timed_out = False
    for values in candidates:
        if time.perf_counter() > deadline:
            timed_out = True
            break
        energy = expected_energy(values)
        evaluated_iters += 1
        if energy < best_energy:
            best_energy = energy
            best_params = values

    # Final high-shot sampling at the best parameters.
    final = tqc.assign_parameters(
        {
            **{gammas[i]: best_params[i] for i in range(p)},
            **{betas[i]: best_params[p + i] for i in range(p)},
        }
    )
    counts = sampler.run([(final,)], shots=shots).result()[0].data.meas.get_counts()
    total_shots = sum(counts.values())
    runtime = time.perf_counter() - start

    samples: list[QuantumSampleResult] = []
    feasible_shots = 0
    optimum_bits = (
        evaluator.evaluate(set(optimum_selection)).selected_opportunity_ids
        if optimum_selection is not None
        else None
    )
    exact_in_samples = False
    for qbits, count in counts.items():
        bits = qbits[::-1]  # convert to canonical variable order
        ev = evaluator.evaluate_bitstring(bits)
        sample = QuantumSampleResult(
            bitstring=bits,
            count=count,
            probability=count / total_shots,
            feasible=ev.feasible,
            raw_mission_value=ev.raw_mission_value,
            objective_value=ev.objective_value,
            qubo_energy=qubo_energy(qubo, bits),
            violations_count=len(ev.violations),
        )
        samples.append(sample)
        if ev.feasible:
            feasible_shots += count
        if optimum_bits is not None and ev.selected_opportunity_ids == optimum_bits and ev.feasible:
            exact_in_samples = True
    samples.sort(key=lambda s: (-s.count, s.bitstring))

    feasible = [s for s in samples if s.feasible]
    infeasible = [s for s in samples if not s.feasible]
    best_feasible = max(
        feasible, key=lambda s: (s.objective_value, s.count, s.bitstring), default=None
    )
    best_infeasible = min(
        infeasible, key=lambda s: (s.qubo_energy, -s.count, s.bitstring), default=None
    )
    gap = (
        known_optimum - best_feasible.objective_value
        if known_optimum is not None and best_feasible is not None
        else None
    )
    selected_schedule = None
    selected_eval = None
    if best_feasible is not None:
        full = evaluator.evaluate_bitstring(best_feasible.bitstring)
        from orbitmind.optimization.models import CandidateSchedule

        selected_schedule = CandidateSchedule(
            problem_checksum=problem.checksum,
            selected_opportunity_ids=full.selected_opportunity_ids,
            produced_by="quantum-qaoa",
        )
        selected_eval = full

    metadata = QuantumCircuitMetadata(
        qubits=n,
        depth=tqc.depth(),
        gate_counts={k: int(v) for k, v in tqc.count_ops().items()},
        shots=shots,
        optimizer_iterations=evaluated_iters,
        qaoa_layers=p,
        simulator_backend="AerSimulator",
        transpile_level=config.transpile_level,
        seed_simulator=config.seed,
        seed_transpiler=config.seed,
        best_parameters={
            **{f"gamma_{i}": best_params[i] for i in range(p)},
            **{f"beta_{i}": best_params[p + i] for i in range(p)},
        },
    )
    status = ExperimentStatus.TIMED_OUT if timed_out else ExperimentStatus.COMPLETED
    return base.model_copy(
        update={
            "status": status,
            "circuit_metadata": metadata,
            "total_shots": total_shots,
            "distinct_samples": len(samples),
            "feasible_sample_ratio": feasible_shots / total_shots if total_shots else 0.0,
            "best_feasible_sample": best_feasible,
            "best_infeasible_sample": best_infeasible,
            "exact_optimum_in_samples": (None if optimum_bits is None else exact_in_samples),
            "objective_gap": gap,
            "selected_schedule": selected_schedule,
            "selected_evaluation": selected_eval,
            "samples": samples,
            "runtime_seconds": runtime,
        }
    )
