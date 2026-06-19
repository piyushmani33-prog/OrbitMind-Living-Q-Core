# Risk Register — OrbitMind Living Q-Core

Severity: Low / Medium / High. Status: Open / Mitigated / Accepted.

| ID | Risk | Sev | Status | Mitigation |
|----|------|-----|--------|------------|
| R-001 | Reference documents ("OrbitMind Living Q-Core", "Feasibility Brief") are absent — **confirmed absent a 2nd time on 2026-06-19** at the start of Phase 2; build continues from the owner prompts as the authoritative spec. | Med | **Open (re-confirmed)** | `REFERENCE_MANIFEST.md` records the absence (no invented checksums); `REFERENCE_RECONCILIATION.md` reconciles the implementation against the build prompt instead. Close only after the real documents are inspected. |
| R-002 | Local interpreter is Python 3.14.4, ahead of the 3.12 production baseline; future deps may lack 3.14 wheels. | Med | Mitigated | Phase 0/1 deps verified to resolve as cp314 wheels; production baseline pinned to 3.12 in ADR-0002; `requires-python>=3.12`. |
| R-003 | Sample TLE elements are stale and not live truth; risk of being misread as live satellite data. | High | Mitigated | `test_only` flag + provenance + epistemic labeling; README & API docs state explicitly; SR-05 enforced. |
| R-004 | SGP4 accuracy degrades for epochs far from the TLE epoch; results could mislead. | Med | Mitigated | Verification checks altitude/coordinate sanity; epistemic status = deterministic-calculation (model of reality, not truth); duration bounded. |
| R-005 | Path traversal when writing artifacts using mission-derived paths. | High | Mitigated | UUID-validated mission id + artifacts-root containment check (SR-13/14) + test. |
| R-006 | Module-boundary erosion in a monolith over time. | Low | Open | MODULE_BOUNDARIES.md dependency rule; code review; import-linter planned (Phase 2). |
| R-007 | Floating-point nondeterminism across platforms breaks "reproducible" claim. | Low | Mitigated | Compare with tolerances; record sgp4/numpy versions in sidecars; deterministic algorithm. |
| R-008 | Dependency supply-chain / unpinned upgrades. | Med | Open | Version constraints in pyproject; `--only-binary` installs; dependency review + secret scanning planned in CI. |
| R-009 | Quantum adapter accidentally invoked on the mission path (perf/appearance). | Low | Mitigated | Slice does not import `quantum`; self-test is manual; capabilities only reports availability. |
| R-010 | mypy/ruff/pytest tool versions on 3.14 behave unexpectedly. | Low | Mitigated | Tools installed and run; results reported with exact output at phase boundaries. |
| R-011 | Secrets accidentally committed. | High | Mitigated | `.gitignore` excludes `.env`, DBs, artifacts; only `.env.example` tracked; no secrets in code. |
| R-012 | CelesTrak GP endpoint URL and licensing terms are not confirmed by any available reference/official doc accessible offline. | Med | Open | Endpoint is **configurable** (not hard-coded), HTTPS + hostname allowlisted; default network DISABLED; offline fixtures used for all tests; licensing recorded as "requires review", no commercial-rights claim (ADR-0008). |
| R-013 | External (CelesTrak) data could be misread as live/authoritative. | High | Mitigated | Freshness states (test-fixture/current/fresh/aging/stale/expired/unavailable/invalid); provenance + cache status on every external-source result; no silent fallback to sample data (ADR-0010). |
| R-014 | Uncontrolled refresh storm / over-polling the external source. | Med | Mitigated | Minimum refresh interval enforced per source policy; in-process lock; cache-first reads; no background polling daemon (ADR-0010). |
