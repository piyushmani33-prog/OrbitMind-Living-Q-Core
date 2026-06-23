"""Selected quantum evidence is signed + independently recomputed (final acceptance, High 1).

Tampering the denormalized best feasible/infeasible sample, the selected schedule, or the selected
evaluation must fail BOTH semantic verification and execution-receipt verification.
"""

from __future__ import annotations

import copy

import pytest

from orbitmind.api.container import AppContainer
from orbitmind.optimization import fixtures
from orbitmind.persistence.optimization_models import QuantumExperimentRow
from orbitmind.quantum.adapter import quantum_available


def _quantum_run(container: AppContainer):
    svc = container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run, _ = svc.benchmark(problem.id, seed=7, shots=128, optimizer_iterations=6, run_quantum=True)
    q = run.quantum_experiment
    if q is None or q.status.value != "completed":
        pytest.skip("quantum experiment did not complete")
    if q.best_infeasible_sample is None or q.selected_evaluation is None:
        pytest.skip("run produced no infeasible sample / selected evaluation to tamper")
    assert svc.read_benchmark_evidence(run.id).authenticated
    return run, q


def _mutate_experiment_json(container: AppContainer, experiment_id: str, mutate) -> None:
    session = container.database.session()
    qrow = session.get(QuantumExperimentRow, experiment_id)
    blob = copy.deepcopy(dict(qrow.experiment_json))  # deep copy so nested edits persist cleanly
    mutate(blob)
    qrow.experiment_json = blob
    session.commit()
    session.close()


@pytest.mark.skipif(not quantum_available(), reason="qiskit/qiskit-aer not installed")
@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda b: b["best_feasible_sample"].__setitem__(
                "qubo_energy", b["best_feasible_sample"]["qubo_energy"] + 123.0
            ),
            id="best_feasible.qubo_energy",
        ),
        pytest.param(
            lambda b: b["best_feasible_sample"].__setitem__(
                "violations_count", b["best_feasible_sample"]["violations_count"] + 5
            ),
            id="best_feasible.violations_count",
        ),
        pytest.param(
            lambda b: b["best_infeasible_sample"].__setitem__(
                "objective_value", b["best_infeasible_sample"]["objective_value"] + 123.0
            ),
            id="best_infeasible.objective_value",
        ),
        pytest.param(
            lambda b: b["selected_schedule"].__setitem__("produced_by", "forged-producer"),
            id="selected_schedule.produced_by",
        ),
        pytest.param(
            lambda b: b["selected_schedule"].__setitem__("problem_checksum", "forged"),
            id="selected_schedule.problem_checksum",
        ),
        pytest.param(
            lambda b: b["selected_evaluation"].__setitem__(
                "objective_value", b["selected_evaluation"]["objective_value"] + 123.0
            ),
            id="selected_evaluation.objective_value",
        ),
        pytest.param(
            lambda b: b["selected_evaluation"].__setitem__(
                "raw_mission_value", b["selected_evaluation"]["raw_mission_value"] + 123.0
            ),
            id="selected_evaluation.raw_mission_value",
        ),
    ],
)
def test_selected_evidence_tamper_fails_reauth(container: AppContainer, mutate) -> None:
    run, q = _quantum_run(container)
    _mutate_experiment_json(container, q.id, mutate)
    auth = container.optimization_service.read_benchmark_evidence(run.id)
    assert auth.integrity_failed and not auth.authenticated
    assert auth.safe_conclusion() == "insufficient-evidence"
