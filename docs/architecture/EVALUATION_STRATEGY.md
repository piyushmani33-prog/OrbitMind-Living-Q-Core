# Evaluation Strategy — OrbitMind Living Q-Core

Measurable checks; each maps to automated tests where possible.

| Dimension | Phase 1 method | Where |
|-----------|----------------|-------|
| API schema correctness | Pydantic models + FastAPI; integration tests assert response schema | tests/integration |
| Workflow determinism | Same input → identical samples (byte-stable floats within tolerance) | tests/unit, integration |
| Source & citation completeness | Assert `ProvenanceRecord` + `OrbitalSourceRecord` present and complete | tests/unit |
| Calculation correctness | Compare SGP4 output against known reference values for the bundled TLE | tests/unit |
| Verification correctness | Each check produces expected status on crafted good/bad inputs | tests/unit |
| Epistemic labeling | Outputs carry a valid `EpistemicStatus`; deterministic calc never labeled "verified-fact" | tests/unit |
| Hallucination / unsupported claim | No LLM on path; assert no free-text claim is labeled verified-fact | tests/unit |
| Visual-output correctness | Both artifacts created, non-empty, sidecar metadata valid + checksum matches | tests/integration |
| Persistence/retrieval | Mission round-trips through repositories; retrieval endpoints return it | tests/integration |
| Failure behavior | Failed propagation → `failed` status + finding + audit, not a crash | tests/integration |
| Migration | Alembic upgrade head builds the schema the ORM expects | tests/integration |
| Latency | 24h/60s propagation < 2s (informational assertion/benchmark) | tests/unit (loose) |
| Offline guarantee | No socket access during tests (design + review; no network code exists) | review |

## Quantum-vs-classical (future, Phase 4)
A quantum result is acceptable only with: a classical baseline, identical problem
definition, reproducible seeds/shots, and a wall-clock + objective comparison. No
"quantum advantage" claim without that evidence (ADR-0005).

## Reporting
`pytest --cov=orbitmind --cov-report=term-missing` produces coverage. Exact command
output is reported at each phase boundary; skipped tests are disclosed.
