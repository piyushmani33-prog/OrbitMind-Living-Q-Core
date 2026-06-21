"""Simulator-only QAOA experiment for bounded scheduling (Aer; no real hardware).

A small, manually-built QAOA circuit minimizes the QUBO energy; parameters are chosen by
a deterministic, bounded grid/seeded search. Every sampled bitstring is independently
re-evaluated by the shared Evaluator — the most frequent sample is NOT assumed best. The
result records full circuit metadata, seeds, and feasible/infeasible sample diagnostics.

Bit-order convention: Aer returns measurement strings with qubit 0 as the RIGHTMOST
character; we reverse to the canonical variable order (index 0 first) before decoding.
"""

from __future__ import annotations

import contextlib
import multiprocessing as mp
import os
import time
from queue import Empty
from typing import Any

from orbitmind.optimization.evaluation import Evaluator
from orbitmind.optimization.evidence import build_evidence_manifest
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

_TIMED_OUT_LIMITATIONS = (
    "Partial/no evidence: the WHOLE quantum experiment (QUBO prep, circuit build, "
    "transpilation, parameter search, sampling, decoding) exceeded the wall-clock timeout "
    "and the isolated worker was terminated. No completed quantum solution; this run is "
    "non-positive by policy and is not registered as competitive evidence."
)


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


def _maybe_test_sleep() -> None:
    """Test-only hook to simulate an expensive operation (gated by an env var; no prod use)."""
    delay = os.environ.get("ORBITMIND_QUANTUM_TEST_SLEEP")
    if delay:
        time.sleep(float(delay))


def _quantum_worker(
    problem_json: dict[str, Any],
    config_json: dict[str, Any],
    known_optimum: float | None,
    optimum_selection: list[str] | None,
    queue: Any,
) -> None:
    """Runs the bounded quantum computation in an isolated child process (review finding #3)."""
    try:
        problem = SchedulingProblem.model_validate(problem_json)
        config = SolverConfiguration.model_validate(config_json)
        evaluator = Evaluator(problem)
        base = QuantumExperiment(
            problem_checksum=problem.checksum,
            status=ExperimentStatus.PENDING,
            configuration=config,
            seed=config.seed,
            software_versions=_software_versions(),
        )
        result = _run(
            problem,
            config,
            evaluator,
            base,
            known_optimum,
            tuple(optimum_selection) if optimum_selection else None,
        )
        queue.put(result.model_dump(mode="json"))
    except Exception as exc:  # pragma: no cover - surfaced to the parent as FAILED
        queue.put({"__error__": f"{type(exc).__name__}: {exc}"})


def _terminate(proc: Any) -> None:
    """Terminate and reap a worker process; never leave an orphan."""
    if proc.is_alive():
        proc.terminate()
        proc.join(5)
    if proc.is_alive():  # pragma: no cover - escalation path
        proc.kill()
        proc.join(5)
    with contextlib.suppress(Exception):  # pragma: no cover - already closed
        proc.close()


def run_quantum_experiment(
    problem: SchedulingProblem,
    config: SolverConfiguration,
    evaluator: Evaluator | None = None,
    *,
    known_optimum: float | None = None,
    optimum_selection: tuple[str, ...] | None = None,
) -> QuantumExperiment:
    """Run a bounded Aer QAOA experiment in an ISOLATED child process with a hard,
    whole-experiment wall-clock timeout (review finding #3). On expiry the worker is
    terminated, no final sampling completes, and the status is ``timed-out`` (never a
    positive conclusion). Runtime is measured from before the first experiment operation.
    """
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

    # Penalty proof gate (review finding #13): the QUBO must NOT be executed on Aer unless the
    # penalty is proven sufficient (or no encoded constraints apply). Contradictory encoded
    # constraints, an unsafe penalty, or an unproven (large custom) penalty stop here BEFORE
    # any circuit is built or any sampler runs — the run is non-positive by policy.
    from orbitmind.optimization.penalties import penalty_policy, proof_allows_execution

    policy = penalty_policy(problem)
    if not proof_allows_execution(policy.proof_status):
        return base.model_copy(
            update={
                "status": ExperimentStatus.INCONCLUSIVE,
                "error": (
                    f"penalty proof status '{policy.proof_status.value}' is not executable; "
                    "QUBO was not built or sampled on Aer"
                ),
                "limitations": (
                    "The QUBO penalty was not proven sufficient (status "
                    f"'{policy.proof_status.value}'). No circuit was built and no Aer sampling "
                    "occurred; this run is non-positive by policy and is not competitive evidence."
                ),
            }
        )

    ctx = mp.get_context("spawn")
    queue: Any = ctx.Queue()
    proc = ctx.Process(
        target=_quantum_worker,
        args=(
            problem.model_dump(mode="json"),
            config.model_dump(mode="json"),
            known_optimum,
            list(optimum_selection) if optimum_selection else None,
            queue,
        ),
        daemon=True,
    )
    started = time.perf_counter()
    proc.start()
    payload: Any = None
    timed_out = False
    try:
        payload = queue.get(timeout=config.timeout_seconds)
    except Empty:
        timed_out = True
    _terminate(proc)  # single cleanup; never leaves an orphan
    runtime = time.perf_counter() - started

    if timed_out:
        return base.model_copy(
            update={
                "status": ExperimentStatus.TIMED_OUT,
                "runtime_seconds": runtime,
                "error": "quantum experiment exceeded the timeout and was terminated",
                "limitations": _TIMED_OUT_LIMITATIONS,
            }
        )
    if isinstance(payload, dict) and "__error__" in payload:
        return base.model_copy(
            update={
                "status": ExperimentStatus.FAILED,
                "error": str(payload["__error__"]),
                "runtime_seconds": runtime,
            }
        )
    experiment = QuantumExperiment.model_validate(payload)
    return experiment.model_copy(update={"runtime_seconds": runtime})


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
    candidates = _candidate_params(p, iterations, config.seed)
    best_params = candidates[0]
    best_energy = float("inf")
    evaluated_iters = 0
    for values in candidates:
        energy = expected_energy(values)
        evaluated_iters += 1
        if energy < best_energy:
            best_energy = energy
            best_params = values

    _maybe_test_sleep()  # test hook: simulate expensive work so the parent timeout can fire

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
    # The worker always runs to completion; the timeout is enforced by the parent process
    # which terminates this worker (so a worker-produced result is always COMPLETED).
    return base.model_copy(
        update={
            "status": ExperimentStatus.COMPLETED,
            "circuit_metadata": metadata,
            "evidence": build_evidence_manifest(problem, config),
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
