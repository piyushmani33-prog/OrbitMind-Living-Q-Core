"""Bounded optimization benchmark artifacts + sidecars (Phase 4A).

Charts are labelled ``model-estimate``. A circuit diagram is NOT proof of useful quantum
performance; it is documentation of the experiment that was run on a simulator.
"""

from __future__ import annotations

import json
import platform
from collections.abc import Mapping
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
from orbitmind.verification.models import VerificationFinding

_DISCLAIMER = (
    "model-estimate; bounded simulator benchmark on a tiny fixture. A circuit diagram is "
    "NOT evidence of quantum advantage. Not a production tasking decision."
)


class OptimizationVisualizationService:
    def __init__(self, artifacts_root: Path) -> None:
        self._root = artifacts_root

    def _scope_dir(self, scope_id: str) -> Path:
        if not is_valid_uuid(scope_id):
            raise ValueError("scope id is not a valid identifier")
        target = ensure_within(self._root, self._root / scope_id)
        target.mkdir(parents=True, exist_ok=True)
        return target

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
        scope = self._scope_dir(run.id)
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
            path = scope / name
            checksum = sha256_file(path)
            sidecar = path.with_suffix(path.suffix + ".json")
            body: dict[str, object] = {
                "artifact_type": art_type,
                "problem_checksum": problem.checksum,
                "solver": solver,
                "created_at": utcnow().isoformat(),
                "software_versions": software,
                "seed": seed,
                "epistemic_status": "model-estimate",
                "verification_summary": verification,
                "checksum": checksum,
                "limitations": _DISCLAIMER,
            }
            if solver == "quantum-qaoa" and evidence_json is not None:
                # Bit-order, QUBO checksum, variable mapping, penalty + proof status, manifest
                # checksum, post-verification requirement, seeds, versions (review #16/#17).
                body["quantum_evidence"] = evidence_json
            sidecar.write_text(json.dumps(body, indent=2), encoding="utf-8")
            artifacts.append(
                {
                    "type": art_type,
                    "path": str(path.relative_to(self._root)),
                    "sidecar_path": str(sidecar.relative_to(self._root)),
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
