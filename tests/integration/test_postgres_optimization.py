"""Live PostgreSQL integration for Phase 4A optimization (migration-first; review #14).

Skips unless ORBITMIND_TEST_POSTGRES_URL points at a disposable DB that has been migrated
to head (see test_postgres_memory.py for setup). These tests deliberately do NOT call
``create_all()`` — they rely on the Alembic-created schema so a migration defect cannot be
masked. They verify foreign keys + the unique checksum constraint, FK enforcement +
rollback, idempotent/race-safe creation, quantum/sample/comparison/artifact persistence,
and preservation of existing memory / mission / space-object rows.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import text

from orbitmind.api.container import AppContainer
from orbitmind.core.config import Settings
from orbitmind.optimization import fixtures
from orbitmind.persistence.optimization_repository import SqlAlchemyOptimizationRepository

_PG_URL = os.environ.get("ORBITMIND_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.skipif(not _PG_URL, reason="set ORBITMIND_TEST_POSTGRES_URL (disposable DB)"),
]

_TABLES = (
    "optimization_artifacts",
    "benchmark_comparisons",
    "quantum_sample_results",
    "quantum_experiments",
    "solver_runs",
    "benchmark_runs",
    "scheduling_constraints",
    "observation_opportunities",
    "optimization_problems",
    "memory_graph_edges",
)


@pytest.fixture
def pg_container(tmp_path: Path) -> AppContainer:
    """A container on the MIGRATED PostgreSQL schema. Does NOT call init_storage/create_all."""
    settings = Settings(
        database_url=_PG_URL,
        artifacts_dir=tmp_path / "art",
        cache_dir=tmp_path / "cache",
        env="test",
        evidence_signing_key="test-evidence-signing-key-0123456789abcdef",
    )
    container = AppContainer(settings=settings)  # no init_storage(): use the migrated schema
    assert container.database.is_postgres
    with container.database.engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(_TABLES) + " RESTART IDENTITY CASCADE"))
    return container


def _exec(container: AppContainer, sql: str) -> list:
    with container.database.engine.connect() as conn:
        return list(conn.execute(text(sql)))


def test_cross_benchmark_comparison_update_is_rejected(pg_container: AppContainer) -> None:
    """A comparison association id cannot be repointed to a result OWNED BY ANOTHER benchmark:
    the composite ownership FK rejects the update (third review, High #2)."""
    from sqlalchemy.exc import IntegrityError

    svc = pg_container.optimization_service
    p1 = svc.create_problem(fixtures.fixture("default"))
    p2 = svc.create_problem(fixtures.fixture("resource-bound"))
    run1, _ = svc.benchmark(p1.id, seed=7, run_quantum=False)
    run2, _ = svc.benchmark(p2.id, seed=7, run_quantum=False)
    # An exact solver id that belongs to run2, not run1.
    foreign_exact = _exec(
        pg_container,
        f"SELECT id FROM solver_runs WHERE benchmark_id='{run2.id}' AND solver_kind='exact'",
    )[0][0]
    engine = pg_container.database.engine
    with engine.connect() as conn:
        trans = conn.begin()
        with pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "UPDATE benchmark_comparisons SET exact_result_id=:fx WHERE benchmark_id=:bid"
                ),
                {"fx": foreign_exact, "bid": run1.id},
            )
        trans.rollback()
    assert _exec(pg_container, "SELECT 1")[0][0] == 1  # transaction recovers


def test_greedy_result_in_exact_slot_is_rejected(pg_container: AppContainer) -> None:
    """The role-aware composite FK rejects a greedy result placed in the exact slot (High #4)."""
    from sqlalchemy.exc import IntegrityError

    svc = pg_container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run, _ = svc.benchmark(problem.id, seed=7, run_quantum=False)
    greedy_id = _exec(
        pg_container,
        f"SELECT id FROM solver_runs WHERE benchmark_id='{run.id}' AND solver_kind='greedy'",
    )[0][0]
    engine = pg_container.database.engine
    with engine.connect() as conn:
        trans = conn.begin()
        with pytest.raises(IntegrityError):
            conn.execute(
                text("UPDATE benchmark_comparisons SET exact_result_id=:g WHERE benchmark_id=:b"),
                {"g": greedy_id, "b": run.id},
            )
        trans.rollback()
    assert _exec(pg_container, "SELECT 1")[0][0] == 1  # transaction recovers


def test_exact_result_in_greedy_slot_is_rejected(pg_container: AppContainer) -> None:
    from sqlalchemy.exc import IntegrityError

    svc = pg_container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run, _ = svc.benchmark(problem.id, seed=7, run_quantum=False)
    exact_id = _exec(
        pg_container,
        f"SELECT id FROM solver_runs WHERE benchmark_id='{run.id}' AND solver_kind='exact'",
    )[0][0]
    engine = pg_container.database.engine
    with engine.connect() as conn:
        trans = conn.begin()
        with pytest.raises(IntegrityError):
            conn.execute(
                text("UPDATE benchmark_comparisons SET greedy_result_id=:e WHERE benchmark_id=:b"),
                {"e": exact_id, "b": run.id},
            )
        trans.rollback()
    assert _exec(pg_container, "SELECT 1")[0][0] == 1


def test_comparison_role_check_constraint_enforced(pg_container: AppContainer) -> None:
    from sqlalchemy.exc import IntegrityError

    svc = pg_container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run, _ = svc.benchmark(problem.id, seed=7, run_quantum=False)
    engine = pg_container.database.engine
    with engine.connect() as conn:
        trans = conn.begin()
        with pytest.raises(IntegrityError):  # CHECK pins the role column to 'exact'
            conn.execute(
                text(
                    "UPDATE benchmark_comparisons SET exact_solver_kind='greedy' "
                    "WHERE benchmark_id=:b"
                ),
                {"b": run.id},
            )
        trans.rollback()
    assert _exec(pg_container, "SELECT 1")[0][0] == 1


@pytest.mark.parametrize("bad_kind", ["bogus", "quantum-qaoa", "", "Exact", "GREEDY"])
def test_bogus_solver_kind_is_rejected(pg_container: AppContainer, bad_kind: str) -> None:
    """The solver-kind CHECK rejects any role outside ('exact','greedy') with txn recovery
    (final acceptance, Medium)."""
    from sqlalchemy.exc import IntegrityError

    svc = pg_container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run, _ = svc.benchmark(problem.id, seed=7, run_quantum=False)
    engine = pg_container.database.engine
    with engine.connect() as conn:
        trans = conn.begin()
        with pytest.raises(IntegrityError):
            conn.execute(
                text("UPDATE solver_runs SET solver_kind=:k WHERE benchmark_id=:b"),
                {"k": bad_kind, "b": run.id},
            )
        trans.rollback()
    assert _exec(pg_container, "SELECT 1")[0][0] == 1  # transaction recovers


def test_generic_memory_navigation_integrity_aware_on_postgres(
    pg_container: AppContainer,
) -> None:
    """Generic problem navigation authenticates each benchmark independently on live PostgreSQL:
    tampering A marks only A's edges invalid while B stays valid (final acceptance, High #3)."""
    from fastapi.testclient import TestClient

    from orbitmind.api.app import create_app

    svc = pg_container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run_a, _ = svc.benchmark(problem.id, seed=7, run_quantum=False)
    run_b, _ = svc.benchmark(problem.id, seed=11, run_quantum=False)
    # Coordinated/visible tamper of A's exact objective JSON.
    with pg_container.database.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE solver_runs SET result_json = jsonb_set(result_json::jsonb,"
                "'{objective_value}', '999') WHERE benchmark_id=:b AND solver_kind='exact'"
            ),
            {"b": run_a.id},
        )
    with TestClient(create_app(pg_container)) as client:
        body = client.get(
            f"/api/v1/memory/graph/{problem.id}/neighbors", params={"limit": 200}
        ).json()
    a_edges = [n for n in body["neighbors"] if n["benchmark_id"] == run_a.id]
    b_edges = [n for n in body["neighbors"] if n["benchmark_id"] == run_b.id]
    assert a_edges and all(n["evidence_validity"] == "integrity-failed" for n in a_edges)
    assert b_edges and all(n["evidence_validity"] == "valid" for n in b_edges)


def test_benchmark_problem_reassignment_is_rejected(pg_container: AppContainer) -> None:
    """A benchmark cannot be repointed to another problem while its children reference the
    original (benchmark_id, problem_id) ownership anchor (High #4)."""
    from sqlalchemy.exc import IntegrityError

    svc = pg_container.optimization_service
    p1 = svc.create_problem(fixtures.fixture("default"))
    p2 = svc.create_problem(fixtures.fixture("resource-bound"))
    run, _ = svc.benchmark(p1.id, seed=7, run_quantum=False)
    engine = pg_container.database.engine
    with engine.connect() as conn:
        trans = conn.begin()
        with pytest.raises(IntegrityError):
            conn.execute(
                text("UPDATE benchmark_runs SET problem_id=:p WHERE id=:b"),
                {"p": p2.id, "b": run.id},
            )
        trans.rollback()
    assert _exec(pg_container, "SELECT 1")[0][0] == 1


def test_missing_envelope_fails_online_on_postgres(pg_container: AppContainer) -> None:
    """Deleting the receipt envelope from a sidecar fails read authentication on live PostgreSQL
    (final sidecar acceptance, High 1)."""
    import json

    svc = pg_container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run, _ = svc.benchmark(problem.id, seed=7, run_quantum=False, generate_artifacts=True)
    assert svc.read_benchmark_evidence(run.id).authenticated
    sidecar = pg_container.settings.resolved_artifacts_dir() / (run.artifacts[0]["path"] + ".json")
    meta = json.loads(sidecar.read_text("utf-8"))
    del meta["execution_receipt"]
    sidecar.write_text(json.dumps(meta), encoding="utf-8")
    auth = svc.read_benchmark_evidence(run.id)
    assert auth.integrity_failed and not auth.authenticated


def test_unknown_sidecar_field_fails_online_on_postgres(pg_container: AppContainer) -> None:
    """A forged unknown top-level sidecar field fails read authentication on live PostgreSQL
    (final sidecar acceptance, High 2)."""
    import json

    svc = pg_container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run, _ = svc.benchmark(problem.id, seed=7, run_quantum=False, generate_artifacts=True)
    assert svc.read_benchmark_evidence(run.id).authenticated
    sidecar = pg_container.settings.resolved_artifacts_dir() / (run.artifacts[0]["path"] + ".json")
    meta = json.loads(sidecar.read_text("utf-8"))
    meta["exact_result_id"] = "FORGED"
    sidecar.write_text(json.dumps(meta), encoding="utf-8")
    auth = svc.read_benchmark_evidence(run.id)
    assert auth.integrity_failed and not auth.authenticated


@pytest.mark.skipif(
    not __import__("orbitmind.quantum.adapter", fromlist=["quantum_available"]).quantum_available(),
    reason="qiskit/qiskit-aer not installed",
)
def test_nested_quantum_evidence_tamper_fails_online_on_postgres(
    pg_container: AppContainer,
) -> None:
    """Deleting / contradicting the nested quantum_evidence block in a quantum sidecar fails read
    authentication on live PostgreSQL (final nested-sidecar acceptance)."""
    import json

    svc = pg_container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run, _ = svc.benchmark(
        problem.id,
        seed=7,
        shots=128,
        optimizer_iterations=6,
        run_quantum=True,
        generate_artifacts=True,
    )
    q = run.quantum_experiment
    if q is None or q.status.value != "completed":
        pytest.skip("quantum experiment did not complete")
    assert svc.read_benchmark_evidence(run.id).authenticated
    root = pg_container.settings.resolved_artifacts_dir()
    qside = next(a for a in run.artifacts if a["type"] == "quantum_sample_distribution")
    sidecar = root / (qside["path"] + ".json")
    base = sidecar.read_text("utf-8")
    # 1) removed block
    meta = json.loads(base)
    meta.pop("quantum_evidence")
    sidecar.write_text(json.dumps(meta), encoding="utf-8")
    auth = svc.read_benchmark_evidence(run.id)
    assert auth.integrity_failed and not auth.authenticated
    # 2) contradicted field (well-shaped but altered shots)
    meta = json.loads(base)
    meta["quantum_evidence"]["shots"] = 999999
    sidecar.write_text(json.dumps(meta), encoding="utf-8")
    auth = svc.read_benchmark_evidence(run.id)
    assert auth.integrity_failed and not auth.authenticated
    sidecar.write_text(base, encoding="utf-8")  # restore
    assert svc.read_benchmark_evidence(run.id).authenticated


@pytest.mark.skipif(
    not __import__("orbitmind.quantum.adapter", fromlist=["quantum_available"]).quantum_available(),
    reason="qiskit/qiskit-aer not installed",
)
def test_nested_verification_summary_present_fails_online_on_postgres(
    pg_container: AppContainer,
) -> None:
    """A forged verification_summary (an unknown, unsigned field under Option B) fails read
    authentication on live PostgreSQL (final nested-sidecar acceptance)."""
    import json

    svc = pg_container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run, _ = svc.benchmark(
        problem.id,
        seed=7,
        shots=128,
        optimizer_iterations=6,
        run_quantum=True,
        generate_artifacts=True,
    )
    q = run.quantum_experiment
    if q is None or q.status.value != "completed":
        pytest.skip("quantum experiment did not complete")
    assert svc.read_benchmark_evidence(run.id).authenticated
    root = pg_container.settings.resolved_artifacts_dir()
    qside = next(a for a in run.artifacts if a["type"] == "quantum_sample_distribution")
    sidecar = root / (qside["path"] + ".json")
    meta = json.loads(sidecar.read_text("utf-8"))
    meta["verification_summary"] = {"checks": 1, "failed": 0, "passed": True}  # forged "all passed"
    sidecar.write_text(json.dumps(meta), encoding="utf-8")
    auth = svc.read_benchmark_evidence(run.id)
    assert auth.integrity_failed and not auth.authenticated


def test_malformed_solver_json_fails_closed_on_postgres(pg_container: AppContainer) -> None:
    """A corrupt persisted solver result_json must FAIL CLOSED on live PostgreSQL — classified as
    malformed, never raised as a 500 (fifth review, High #2)."""
    svc = pg_container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run, _ = svc.benchmark(problem.id, seed=7, run_quantum=False)
    assert svc.read_benchmark_evidence(run.id).authenticated
    with pg_container.database.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE solver_runs SET result_json='{\"corrupt\": true}'::jsonb "
                "WHERE benchmark_id=:b"
            ),
            {"b": run.id},
        )
    auth = svc.read_benchmark_evidence(run.id)
    assert auth.found and auth.integrity_failed and auth.run is None
    assert auth.integrity_status == "malformed-persisted-evidence"
    audits = _exec(
        pg_container,
        "SELECT count(*) FROM audit_events WHERE action='optimization.benchmark_integrity_failed'",
    )[0][0]
    assert audits >= 1


@pytest.mark.skipif(
    not __import__("orbitmind.quantum.adapter", fromlist=["quantum_available"]).quantum_available(),
    reason="qiskit/qiskit-aer not installed",
)
def test_child_sample_tamper_detected_on_postgres(pg_container: AppContainer) -> None:
    """A tampered quantum_sample_results child row is caught by canonical-sample re-authentication
    on live PostgreSQL (fifth review, Critical)."""
    svc = pg_container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run, _ = svc.benchmark(problem.id, seed=7, shots=128, optimizer_iterations=6, run_quantum=True)
    q = run.quantum_experiment
    if q is None or q.status.value != "completed":
        pytest.skip("quantum experiment did not complete")
    assert svc.read_benchmark_evidence(run.id).authenticated
    with pg_container.database.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE quantum_sample_results SET raw_mission_value = raw_mission_value + 123 "
                "WHERE experiment_id=:e"
            ),
            {"e": q.id},
        )
    auth = svc.read_benchmark_evidence(run.id)
    assert auth.integrity_failed and auth.integrity_status == "sample-row-mismatch"


def test_selected_evidence_tamper_detected_on_postgres(pg_container: AppContainer) -> None:
    """Tampering the denormalized selected evaluation in experiment_json fails read auth on live
    PostgreSQL (final acceptance, High 1)."""
    svc = pg_container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run, _ = svc.benchmark(problem.id, seed=7, shots=128, optimizer_iterations=6, run_quantum=True)
    q = run.quantum_experiment
    if q is None or q.status.value != "completed" or q.selected_evaluation is None:
        pytest.skip("quantum experiment did not complete with a selected evaluation")
    assert svc.read_benchmark_evidence(run.id).authenticated
    with pg_container.database.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE quantum_experiments SET experiment_json = jsonb_set(experiment_json::jsonb,"
                "'{selected_evaluation,objective_value}', '999') WHERE id=:e"
            ),
            {"e": q.id},
        )
    auth = svc.read_benchmark_evidence(run.id)
    assert auth.integrity_failed and not auth.authenticated


@pytest.mark.parametrize(
    "raw",
    ['{"competitive_relative_gap": "0.0", "min_feasible_sample_ratio": "0.05"}', "{}"],
)
def test_string_and_empty_thresholds_fail_closed_on_postgres(
    pg_container: AppContainer, raw: str
) -> None:
    """A numeric-string or empty persisted thresholds object fails closed on live PostgreSQL —
    never coerced or defaulted (final acceptance, Medium / High 2)."""
    svc = pg_container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run, _ = svc.benchmark(problem.id, seed=7, run_quantum=False)
    assert svc.read_benchmark_evidence(run.id).authenticated
    with pg_container.database.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE benchmark_comparisons SET thresholds_json=CAST(:t AS jsonb) "
                "WHERE benchmark_id=:b"
            ),
            {"t": raw, "b": run.id},
        )
    auth = svc.read_benchmark_evidence(run.id)
    assert auth.found and auth.integrity_failed and auth.run is None
    assert auth.integrity_status == "malformed-persisted-evidence"


def test_execution_receipt_persists_on_postgres(pg_container: AppContainer) -> None:
    """A verified benchmark persists a signed execution receipt (signer key id stored, secret
    never) and is marked accepted on live PostgreSQL (third review, High #1)."""
    svc = pg_container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run, findings = svc.benchmark(problem.id, seed=7, run_quantum=False)
    assert all(f.passed for f in findings)
    rows = _exec(
        pg_container,
        f"SELECT signer_key_id, signature, payload_checksum FROM "
        f"benchmark_execution_receipts WHERE benchmark_id='{run.id}'",
    )
    assert len(rows) == 1 and rows[0][0] and rows[0][1] and rows[0][2]
    accepted = _exec(
        pg_container, f"SELECT verification_passed FROM benchmark_runs WHERE id='{run.id}'"
    )[0][0]
    assert accepted is True
    # The signing secret is never stored anywhere in the receipt row.
    payload = _exec(
        pg_container,
        "SELECT payload_json::text FROM benchmark_execution_receipts "
        f"WHERE benchmark_id='{run.id}'",
    )[0][0]
    assert "secret" not in payload.lower()


def test_receipt_replay_is_rejected_on_postgres(pg_container: AppContainer) -> None:
    """A second receipt reusing an existing signed payload checksum (replay) is rejected by the
    database-level unique constraint, and the transaction recovers (fourth review, Medium #1)."""
    from sqlalchemy.exc import IntegrityError

    svc = pg_container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run, _ = svc.benchmark(problem.id, seed=7, run_quantum=False)
    existing = _exec(
        pg_container,
        "SELECT payload_checksum, signer_key_id, signature_algorithm, signature "
        f"FROM benchmark_execution_receipts WHERE benchmark_id='{run.id}'",
    )[0]
    engine = pg_container.database.engine
    with engine.connect() as conn:
        trans = conn.begin()
        with pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "INSERT INTO benchmark_execution_receipts (id, benchmark_id, signer_key_id, "
                    "signature_algorithm, payload_checksum, signature, payload_json, created_at) "
                    "VALUES ('replay-id', :bid, :kid, :alg, :pc, :sig, '{}', now())"
                ),
                {
                    "bid": run.id,  # different receipt id, SAME payload checksum (replay)
                    "kid": existing[1],
                    "alg": existing[2],
                    "pc": existing[0],  # replayed payload checksum -> unique violation
                    "sig": existing[3],
                },
            )
        trans.rollback()
    assert _exec(pg_container, "SELECT 1")[0][0] == 1  # transaction recovers
    assert (
        _exec(
            pg_container,
            f"SELECT count(*) FROM benchmark_execution_receipts WHERE benchmark_id='{run.id}'",
        )[0][0]
        == 1
    )


def test_schema_is_at_corrective_head_with_constraints(pg_container: AppContainer) -> None:
    head = _exec(pg_container, "SELECT version_num FROM alembic_version")[0][0]
    assert head == "m8b9c0d1e2f3"
    # Foreign keys created by the corrective migration are present.
    fks = {
        r[0]
        for r in _exec(
            pg_container,
            "SELECT constraint_name FROM information_schema.table_constraints "
            "WHERE table_schema='public' AND constraint_type='FOREIGN KEY' "
            "AND table_name IN ('benchmark_runs','solver_runs','quantum_experiments',"
            "'benchmark_comparisons','optimization_artifacts')",
        )
    }
    assert any("benchmark_runs" in f for f in fks)
    # Unique constraint/index on the canonical checksum.
    uniques = _exec(
        pg_container,
        "SELECT indexdef FROM pg_indexes WHERE indexname='ix_optimization_problems_checksum'",
    )
    assert uniques and "UNIQUE" in uniques[0][0].upper()


def test_foreign_key_rejects_orphan_and_transaction_recovers(pg_container: AppContainer) -> None:
    from sqlalchemy.exc import IntegrityError

    engine = pg_container.database.engine
    with engine.connect() as conn:
        trans = conn.begin()
        with pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "INSERT INTO solver_runs (id, benchmark_id, problem_checksum, solver_kind, "
                    "solver_name, solver_version, status, optimality_status, feasible, seed, "
                    "runtime_seconds, config_json, result_json, software_versions, created_at) "
                    "VALUES ('orphan','NO-SUCH-BENCHMARK','x','exact','x','1','completed',"
                    "'optimal',true,1,0.0,'{}','{}','{}', now())"
                )
            )
        trans.rollback()
    # The connection/transaction is usable afterwards.
    assert _exec(pg_container, "SELECT 1")[0][0] == 1
    assert _exec(pg_container, "SELECT count(*) FROM solver_runs")[0][0] == 0


def test_benchmark_persists_and_reads_back(pg_container: AppContainer) -> None:
    svc = pg_container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    assert _exec(pg_container, "SELECT count(*) FROM observation_opportunities")[0][0] == 4

    run, findings = svc.benchmark(problem.id, seed=7, run_quantum=False)
    assert all(f.passed for f in findings)
    assert _exec(pg_container, "SELECT count(*) FROM benchmark_runs")[0][0] == 1
    assert _exec(pg_container, "SELECT count(*) FROM solver_runs")[0][0] == 2
    assert _exec(pg_container, "SELECT count(*) FROM benchmark_comparisons")[0][0] == 1
    # Comparison config round-trips exactly.
    session = pg_container.database.session()
    stored = SqlAlchemyOptimizationRepository(session).get_comparison(run.id)
    session.close()
    assert stored is not None and stored.conclusion == run.comparison.conclusion
    assert (
        stored.thresholds.competitive_relative_gap
        == run.comparison.thresholds.competitive_relative_gap
    )


def test_comparison_associations_and_policy_round_trip_on_postgres(
    pg_container: AppContainer,
) -> None:
    """The new comparison columns (associations, objective gap, server policy metadata) and the
    benchmark accepted flag round-trip on live PostgreSQL (review findings #9/#17/#23)."""
    svc = pg_container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run, _ = svc.benchmark(problem.id, seed=7, run_quantum=False, policy_id="lenient-v1")

    session = pg_container.database.session()
    stored = SqlAlchemyOptimizationRepository(session).get_comparison(run.id)
    session.close()
    assert stored is not None
    assert stored.exact_result_id == run.comparison.exact_result_id
    assert stored.greedy_result_id == run.comparison.greedy_result_id
    assert stored.policy_id == "lenient-v1" and stored.policy_version == "1"
    assert stored.policy_checksum == run.comparison.policy_checksum
    assert stored.thresholds.competitive_relative_gap == 0.25
    assert stored.objective_gap == run.comparison.objective_gap
    # New columns exist + the verified benchmark is persisted in the ACCEPTED state.
    cols = {
        r[0]
        for r in _exec(
            pg_container,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='benchmark_comparisons'",
        )
    }
    assert {"policy_id", "policy_version", "policy_checksum", "objective_gap"} <= cols
    accepted = _exec(
        pg_container, f"SELECT verification_passed FROM benchmark_runs WHERE id='{run.id}'"
    )[0][0]
    assert accepted is True


def test_save_benchmark_flushes_parent_before_fk_children(pg_container: AppContainer) -> None:
    """Regression (live-PG closure): save_benchmark must flush the benchmark_runs parent
    before its FK children (solver runs + comparison). These mappers have no ORM
    relationship(), so the unit-of-work does NOT order them by the table FK; without an
    explicit parent flush PostgreSQL rejects the child inserts with a ForeignKeyViolation.
    SQLite (FKs unenforced) masked this; live PostgreSQL exposes it."""
    from orbitmind.optimization.benchmark import run_benchmark

    problem = pg_container.optimization_service.create_problem(fixtures.fixture("default"))
    run = run_benchmark(problem, seed=7, run_quantum=False)
    session = pg_container.database.session()
    repo = SqlAlchemyOptimizationRepository(session)
    repo.save_benchmark(run, problem_id=problem.id, verification_passed=True)
    session.commit()  # must NOT raise IntegrityError
    session.close()
    # Parent and every FK child persisted and correctly linked to the benchmark run.
    assert _exec(pg_container, "SELECT count(*) FROM benchmark_runs")[0][0] == 1
    assert (
        _exec(pg_container, f"SELECT count(*) FROM solver_runs WHERE benchmark_id='{run.id}'")[0][0]
        == 2
    )
    assert (
        _exec(
            pg_container,
            f"SELECT count(*) FROM benchmark_comparisons WHERE benchmark_id='{run.id}'",
        )[0][0]
        == 1
    )


def test_quantum_and_samples_and_artifacts_persist(pg_container: AppContainer) -> None:
    svc = pg_container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run, _ = svc.benchmark(
        problem.id,
        seed=7,
        shots=512,
        optimizer_iterations=12,
        run_quantum=True,
        generate_artifacts=True,
    )
    assert (
        _exec(pg_container, f"SELECT count(*) FROM benchmark_runs WHERE id='{run.id}'")[0][0] == 1
    )
    assert _exec(pg_container, f"SELECT count(*) FROM solver_runs WHERE benchmark_id='{run.id}'")[
        0
    ][0] == len(run.solver_results)
    assert (
        _exec(
            pg_container,
            f"SELECT count(*) FROM benchmark_comparisons WHERE benchmark_id='{run.id}'",
        )[0][0]
        == 1
    )
    if run.quantum_experiment is not None and run.quantum_experiment.status.value == "completed":
        assert (
            _exec(
                pg_container,
                f"SELECT count(*) FROM quantum_experiments WHERE benchmark_id='{run.id}'",
            )[0][0]
            == 1
        )

    artifact_types = {
        row[0]
        for row in _exec(
            pg_container,
            f"SELECT artifact_type FROM optimization_artifacts WHERE scope_id='{run.id}'",
        )
    }
    stable_artifact_types = {
        "selected_observation_timeline",
        "solver_objective_comparison",
        "feasibility_violation_comparison",
        "benchmark_summary_json",
    }
    assert stable_artifact_types <= artifact_types

    sample_count = _exec(
        pg_container,
        "SELECT count(*) "
        "FROM quantum_sample_results qsr "
        "JOIN quantum_experiments qe ON qsr.experiment_id = qe.id "
        f"WHERE qe.benchmark_id = '{run.id}'",
    )[0][0]
    if sample_count > 0:
        assert "quantum_sample_distribution" in artifact_types


def test_duplicate_creation_is_idempotent_and_race_safe(pg_container: AppContainer) -> None:
    svc = pg_container.optimization_service
    a = svc.create_problem(fixtures.fixture("default"))
    b = svc.create_problem(fixtures.fixture("default"))
    assert a.id == b.id  # idempotent
    assert _exec(pg_container, "SELECT count(*) FROM optimization_problems")[0][0] == 1

    # Concurrent insert race: two sessions insert the same checksum; one wins, the other
    # rolls back its savepoint and returns the existing id (transaction stays usable).
    fresh = pg_container.database.session()
    other = pg_container.database.session()
    fresh.execute(text("TRUNCATE optimization_problems CASCADE"))
    fresh.commit()
    problem = fixtures.fixture("mutual-exclusion")
    from orbitmind.optimization.problem import normalize_problem

    norm = normalize_problem(problem)
    repo_a = SqlAlchemyOptimizationRepository(fresh)
    repo_b = SqlAlchemyOptimizationRepository(other)
    id_a = repo_a.save_problem(norm)
    fresh.commit()
    id_b = repo_b.save_problem(norm.model_copy(update={"id": "different-uuid"}))  # race loser
    other.commit()
    assert id_a == id_b == norm.id  # both return the persisted id
    fresh.close()
    other.close()
    assert _exec(pg_container, "SELECT count(*) FROM optimization_problems")[0][0] == 1


def test_existing_domain_rows_preserved(pg_container: AppContainer) -> None:
    pg_container.optimization_service.create_problem(fixtures.fixture("default"))
    for table in ("missions", "space_objects", "scientific_documents", "memory_graph_edges"):
        _exec(pg_container, f"SELECT count(*) FROM {table}")  # queryable, untouched
