# U8.1A Controlled Tool Gateway Foundation — Correction Review Record

- Date: 2026-07-22
- `governance.epistemic`: deterministic-calculation
- Review state: implementation evidence awaiting fresh independent review

## Corrected production semantics

F1 is corrected by lifecycle-owned transaction scope. The fresh-session guard remains, the error
uses the core validation taxonomy and `tool_gateway_transaction_error`, and fingerprint, replay or
conflict, replay return, verified Admission read, catalog, policy, record construction, and append
share one `session.begin()` transaction. Successful returns commit; all exceptions roll back;
repositories do not commit.

F2 is corrected by an additive verified-identity read on the Admission repository. It performs the
existing owner-scoped lookup and existing fail-closed `_to_domain` verification before exposing
the stored identity. Gateway contracts, ORM, repository mapping, and the in-place migration store a
nullable 64-lowercase-hex `admission_record_identity`. Found records bind the exact identity for
every Admission outcome; misses and cross-owner references bind `None`; corrupt evidence rolls
back; historical replay returns the original binding before any current lookup.

The correction also pins authored public-safe detail text to reason codes, computes the descriptor
checksum once per new evaluation, and uses explicit canonical JSON options for decision checksums.

## Corrected test evidence

The six gateway test files now cover real SQLite transaction durability and restart replay,
conflict and rollback, exact identity binding, found-not-admitted and no-leak misses, corrupt
Admission and Gateway evidence, replay/conflict zero-call sentinels, current-state evaluation,
all 13 precedence rows, deterministic reason ordering, contract grammar and schema rejection,
checksum domain separation, owner isolation, race reconciliation, the closed architecture
allowlist, sanctioned consumers, and absence of adapters, dynamic imports, mutable runtime state,
and execution surfaces. The PostgreSQL test uses real persistence when the disposable
`ORBITMIND_TEST_POSTGRES_URL` is present and covers cross-session durability, restart replay,
verified identity, owner isolation, FK `RESTRICT`, tamper failure, and a synchronized first-write
race with one surviving row and `created`/`replayed` dispositions.

## Validation expectations and status

Focused validation must run in the sealed order: F1, F2, replay/conflict sentinels, all policy
rows, SQLite durability, configured PostgreSQL, architecture, all U8.1A tests, related Admission
tests, stale-head regression, Ruff format/check, strict mypy, Alembic sole-head verification,
disposable SQLite upgrade/downgrade/upgrade, and `git diff --check`. Only after those pass may the
single authorized corrected-candidate complete suite run. Exact command output, JUnit counts,
hashes, and patch evidence belong under the external correction-implementation evidence root.

PostgreSQL is product-passed only when the disposable URL is configured and the real tests run.
Otherwise its status is `environment-blocked, not product-passed`; no unknown credentials may be
used. This document does not invent test counts or claim an unavailable database passed.

## Boundary conclusion

This candidate creates and replays non-executing governance decisions only. It does not invoke a
tool, construct an adapter, produce a receipt or result, contact a provider, mutate a worktree,
deploy, release, spend, control hardware, or begin a later Agent Execution Spine component. Final
acceptance and phase advancement require fresh independent review and explicit human approval.
