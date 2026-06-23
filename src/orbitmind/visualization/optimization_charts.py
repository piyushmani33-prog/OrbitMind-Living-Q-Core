"""Bounded optimization benchmark artifacts + sidecars (Phase 4A).

Charts are labelled ``model-estimate``. A circuit diagram is NOT proof of useful quantum
performance; it is documentation of the experiment that was run on a simulator.
"""

from __future__ import annotations

import json
import platform
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from orbitmind import __version__
from orbitmind.core.checksums import sha256_file
from orbitmind.core.ids import is_valid_uuid
from orbitmind.core.paths import ensure_within
from orbitmind.core.timeutils import utcnow
from orbitmind.optimization.models import BenchmarkRun, SchedulingProblem
from orbitmind.optimization.receipts import (
    ARTIFACT_EPISTEMIC_STATUS,
    ARTIFACT_VERIFICATION_STATE,
    SIDECAR_ARTIFACT_LIMITATIONS,
)
from orbitmind.verification.models import VerificationFinding

# The sidecar disclaimer is the SAME constant the signed canonical artifact entry binds, so the
# sidecar's top-level limitations exactly equals the signed entry (final acceptance, High #1).
_DISCLAIMER = SIDECAR_ARTIFACT_LIMITATIONS


@dataclass(frozen=True)
class CleanupResult:
    """Outcome of an artifact cleanup, with a bounded, secret-free error report (Medium #4)."""

    success: bool
    exception_type: str | None = None
    safe_error_code: str | None = None


class OptimizationVisualizationService:
    def __init__(self, artifacts_root: Path) -> None:
        self._root = artifacts_root

    def _final_dir(self, scope_id: str) -> Path:
        if not is_valid_uuid(scope_id):
            raise ValueError("scope id is not a valid identifier")
        return ensure_within(self._root, self._root / scope_id)

    def _staging_dir(self, scope_id: str) -> Path:
        if not is_valid_uuid(scope_id):
            raise ValueError("scope id is not a valid identifier")
        staging = ensure_within(self._root, self._root / ".staging" / scope_id)
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)
        return staging

    def embed_receipt_into_sidecars(self, run: object, receipt: object) -> None:
        """Embed each artifact's canonical entry + the complete canonical manifest + the signed
        receipt into every promoted sidecar for offline authentication (fifth review, High #1).
        Receipt/entry/manifest bytes are EXCLUDED from the digests the receipt itself signs, so
        this does not invalidate the receipt."""
        from orbitmind.optimization.models import BenchmarkRun
        from orbitmind.optimization.receipts import (
            BenchmarkExecutionReceipt,
            embed_sidecar_evidence,
        )

        assert isinstance(receipt, BenchmarkExecutionReceipt)
        assert isinstance(run, BenchmarkRun)
        for art in run.artifacts:
            sidecar = ensure_within(self._root, self._root / art["sidecar_path"])
            if sidecar.is_file():
                meta = json.loads(sidecar.read_text("utf-8"))
                sidecar.write_text(
                    json.dumps(embed_sidecar_evidence(meta, run, art, receipt), indent=2),
                    encoding="utf-8",
                )

    def cleanup(self, scope_id: str) -> CleanupResult:
        """Idempotently remove a scope's staging + final artifact directories, REPORTING any real
        deletion failure instead of suppressing it (fifth review, Medium #4). No ``suppress`` and
        no ``ignore_errors`` — a failure surfaces as a bounded, secret-free ``CleanupResult``."""
        if not is_valid_uuid(scope_id):
            return CleanupResult(success=True)
        try:
            for d in (self._root / ".staging" / scope_id, self._root / scope_id):
                if d.exists():
                    shutil.rmtree(d)  # raises on a genuine deletion failure
            return CleanupResult(success=True)
        except Exception as exc:
            # Safe, bounded report: NO secrets, NO unrestricted local paths.
            return CleanupResult(
                success=False,
                exception_type=type(exc).__name__,
                safe_error_code="artifact-cleanup-failed",
            )

    def _promote(self, scope_id: str, staging: Path) -> None:
        """Atomically move the staged scope directory into its final location (Medium #3)."""
        final = self._final_dir(scope_id)
        if final.exists():
            shutil.rmtree(final, ignore_errors=True)
        final.parent.mkdir(parents=True, exist_ok=True)
        staging.replace(final)

    def _software(self, run: BenchmarkRun) -> dict[str, str]:
        out = {
            "python": platform.python_version(),
            "orbitmind": __version__,
            "matplotlib": matplotlib.__version__,
        }
        if run.quantum_experiment is not None:
            out.update(run.quantum_experiment.software_versions)
        return out

    def generate(
        self,
        problem: SchedulingProblem,
        run: BenchmarkRun,
        findings: list[VerificationFinding],
        *,
        seed: int,
    ) -> list[dict[str, str]]:
        # Generate into a staging directory, then atomically promote on success (Medium #3); the
        # service removes staging/final on any later failure so no orphan artifacts remain.
        scope = self._staging_dir(run.id)
        software = self._software(run)
        verification = {
            "checks": len(findings),
            "failed": sum(1 for f in findings if not f.passed),
            "passed": all(f.passed for f in findings),
        }
        # Self-describing quantum evidence carried into the summary + quantum sidecars (#16/#17).
        evidence = run.quantum_experiment.evidence if run.quantum_experiment is not None else None
        evidence_json = evidence.model_dump(mode="json") if evidence is not None else None
        artifacts: list[dict[str, str]] = []

        def emit(name: str, art_type: str, solver: str) -> None:
            from orbitmind.optimization.receipts import _media_type_for

            path = scope / name
            checksum = sha256_file(path)
            sidecar = path.with_suffix(path.suffix + ".json")
            body: dict[str, object] = {
                "sidecar_format_version": "1",
                "artifact_type": art_type,
                "media_type": _media_type_for(name),
                # Ownership + policy anchor authenticated by the verifier (third review, High #4).
                "benchmark_id": run.id,
                "problem_id": run.problem_id,
                "problem_checksum": problem.checksum,
                "policy_snapshot_checksum": str((run.policy_snapshot or {}).get("checksum", "")),
                "comparison_algorithm_version": str(
                    (run.policy_snapshot or {}).get("comparison_algorithm_version", "")
                ),
                "solver": solver,
                "created_at": utcnow().isoformat(),
                "software_versions": software,
                "seed": seed,
                "epistemic_status": ARTIFACT_EPISTEMIC_STATUS,
                "verification_summary": verification,
                "verification_state": ARTIFACT_VERIFICATION_STATE,
                "checksum": checksum,
                "limitations": _DISCLAIMER,
            }
            if solver == "quantum-qaoa" and evidence_json is not None:
                # Bit-order, QUBO checksum, variable mapping, penalty + proof status, manifest
                # checksum, post-verification requirement, seeds, versions (review #16/#17).
                body["quantum_evidence"] = evidence_json
            sidecar.write_text(json.dumps(body, indent=2), encoding="utf-8")
            # Record FINAL-location relative paths (the scope dir name), not the staging path.
            artifacts.append(
                {
                    "type": art_type,
                    "path": str(Path(run.id) / name),
                    "sidecar_path": str(Path(run.id) / (name + ".json")),
                    "checksum": checksum,
                }
            )

        self._timeline(problem, run, scope / "selected_timeline.png")
        emit("selected_timeline.png", "selected_observation_timeline", "all")
        self._objective_comparison(run, scope / "objective_comparison.png")
        emit("objective_comparison.png", "solver_objective_comparison", "all")
        self._feasibility_comparison(run, scope / "feasibility_comparison.png")
        emit("feasibility_comparison.png", "feasibility_violation_comparison", "all")

        if run.quantum_experiment is not None and run.quantum_experiment.samples:
            self._sample_distribution(run, scope / "quantum_sample_distribution.png")
            emit("quantum_sample_distribution.png", "quantum_sample_distribution", "quantum-qaoa")
            diagram_name = self._circuit_diagram(problem, run, scope)
            if diagram_name is not None:
                emit(diagram_name, "quantum_circuit_diagram", "quantum-qaoa")

        summary_path = scope / "benchmark_summary.json"
        summary_path.write_text(
            json.dumps(self._summary(problem, run, verification, evidence_json), indent=2),
            encoding="utf-8",
        )
        emit("benchmark_summary.json", "benchmark_summary_json", "all")
        self._promote(run.id, scope)  # atomic staging -> final on success
        return artifacts

    # -- individual charts --------------------------------------------------
    def _selected_ids(self, run: BenchmarkRun) -> set[str]:
        best = None
        for r in run.solver_results:
            if (
                r.feasible
                and r.schedule is not None
                and (best is None or (r.objective_value or 0) > best[0])
            ):
                best = (r.objective_value or 0, set(r.schedule.selected_opportunity_ids))
        return best[1] if best else set()

    def _timeline(self, problem: SchedulingProblem, run: BenchmarkRun, path: Path) -> None:
        selected = self._selected_ids(run)
        sats = sorted({o.satellite_id for o in problem.opportunities})
        fig, ax = plt.subplots(figsize=(8, 3.2))
        base = problem.opportunities[0].window.start
        for opp in sorted(problem.opportunities, key=lambda o: o.id):
            y = sats.index(opp.satellite_id)
            start_min = (opp.window.start - base).total_seconds() / 60.0
            width = (opp.window.end - opp.window.start).total_seconds() / 60.0
            chosen = opp.id in selected
            ax.barh(
                y,
                width,
                left=start_min,
                height=0.5,
                color="#2a7d2a" if chosen else "#c0c0c0",
                edgecolor="black",
                alpha=0.9 if chosen else 0.5,
            )
            ax.text(start_min + width / 2, y, opp.id, ha="center", va="center", fontsize=7)
        ax.set_yticks(range(len(sats)))
        ax.set_yticklabels(sats)
        ax.set_xlabel("minutes from start (UTC)")
        ax.set_title("Selected observation timeline (green = selected) — model-estimate")
        fig.tight_layout()
        fig.savefig(path, dpi=110)
        plt.close(fig)

    def _objective_comparison(self, run: BenchmarkRun, path: Path) -> None:
        labels, values = [], []
        for r in run.solver_results:
            labels.append(r.solver_kind.value)
            values.append(
                r.objective_value if r.feasible and r.objective_value is not None else 0.0
            )
        qe = run.quantum_experiment
        if qe is not None:
            labels.append("quantum-qaoa")
            values.append(
                qe.best_feasible_sample.objective_value if qe.best_feasible_sample else 0.0
            )
        fig, ax = plt.subplots(figsize=(6, 3.6))
        ax.bar(labels, values, color=["#3060c0", "#30a060", "#a05bd0"][: len(labels)])
        if run.comparison and run.comparison.known_optimum is not None:
            ax.axhline(run.comparison.known_optimum, ls="--", color="black", label="known optimum")
            ax.legend()
        ax.set_ylabel("feasible objective (mission value)")
        ax.set_title("Solver objective comparison — model-estimate")
        fig.tight_layout()
        fig.savefig(path, dpi=110)
        plt.close(fig)

    def _feasibility_comparison(self, run: BenchmarkRun, path: Path) -> None:
        labels, feas = [], []
        for r in run.solver_results:
            labels.append(r.solver_kind.value)
            feas.append(1.0 if r.feasible else 0.0)
        qe = run.quantum_experiment
        if qe is not None:
            labels.append("quantum (feasible-sample ratio)")
            feas.append(qe.feasible_sample_ratio)
        fig, ax = plt.subplots(figsize=(6, 3.6))
        ax.bar(labels, feas, color="#3a7")
        ax.set_ylim(0, 1.05)
        ax.set_ylabel("feasible (1.0) / feasible-sample ratio")
        ax.set_title("Feasibility comparison — model-estimate")
        plt.xticks(rotation=15, ha="right", fontsize=8)
        fig.tight_layout()
        fig.savefig(path, dpi=110)
        plt.close(fig)

    def _sample_distribution(self, run: BenchmarkRun, path: Path) -> None:
        qe = run.quantum_experiment
        assert qe is not None
        samples = sorted(qe.samples, key=lambda s: -s.count)[:16]
        fig, ax = plt.subplots(figsize=(8, 3.6))
        colors = ["#2a7d2a" if s.feasible else "#c04040" for s in samples]
        ax.bar([s.bitstring for s in samples], [s.count for s in samples], color=colors)
        ax.set_ylabel("shot count")
        ax.set_title(
            "Quantum sample distribution (green=feasible, red=infeasible) — model-estimate"
        )
        plt.xticks(rotation=60, ha="right", fontsize=7)
        fig.tight_layout()
        fig.savefig(path, dpi=110)
        plt.close(fig)

    def _circuit_diagram(
        self, problem: SchedulingProblem, run: BenchmarkRun, scope: Path
    ) -> str | None:
        """Render the QAOA circuit; prefers matplotlib, falls back to a dependency-free
        text diagram (no pylatexenc/extra packages required). Returns the filename written."""
        from orbitmind.optimization.quantum import build_qaoa_circuit

        layers = run.quantum_experiment.configuration.qaoa_layers if run.quantum_experiment else 1
        qc, _g, _b = build_qaoa_circuit(problem, layers)
        try:
            fig = qc.draw("mpl", fold=-1)
            fig.savefig(scope / "circuit_diagram.png", dpi=100)
            plt.close(fig)
            return "circuit_diagram.png"
        except Exception:  # mpl drawer needs pylatexenc; fall back to text (always works)
            try:
                (scope / "circuit_diagram.txt").write_text(str(qc.draw("text")), encoding="utf-8")
                return "circuit_diagram.txt"
            except Exception:  # pragma: no cover - defensive
                return None

    def _summary(
        self,
        problem: SchedulingProblem,
        run: BenchmarkRun,
        verification: Mapping[str, object],
        evidence_json: dict[str, object] | None = None,
    ) -> dict[str, object]:
        comp = run.comparison
        qe = run.quantum_experiment
        return {
            "problem": {
                "name": problem.name,
                "checksum": problem.checksum,
                "num_variables": len(problem.opportunities),
            },
            # Authoritative, self-describing quantum evidence manifest (review finding #17).
            "quantum_evidence": evidence_json,
            "conclusion": comp.conclusion.value if comp else None,
            "rationale": comp.rationale if comp else None,
            "known_optimum": comp.known_optimum if comp else None,
            "classical": [
                {
                    "solver": r.solver_name,
                    "kind": r.solver_kind.value,
                    "status": r.status.value,
                    "objective": r.objective_value,
                    "feasible": r.feasible,
                    "optimality": r.optimality_status.value,
                    "runtime_seconds": r.runtime_seconds,
                }
                for r in run.solver_results
            ],
            "quantum": None
            if qe is None
            else {
                "status": qe.status.value,
                "qubits": qe.circuit_metadata.qubits if qe.circuit_metadata else None,
                "depth": qe.circuit_metadata.depth if qe.circuit_metadata else None,
                "shots": qe.total_shots,
                "feasible_sample_ratio": qe.feasible_sample_ratio,
                "best_feasible_objective": qe.best_feasible_sample.objective_value
                if qe.best_feasible_sample
                else None,
                "objective_gap": qe.objective_gap,
                "exact_optimum_in_samples": qe.exact_optimum_in_samples,
            },
            "verification": verification,
            "limitations": _DISCLAIMER,
            "generated_at": utcnow().isoformat(),
        }
