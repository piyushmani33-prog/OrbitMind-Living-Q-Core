# ADR-0038 - Authority-Admission Acceptance and Trusted-Local Admission API

- **Status:** Accepted
- **Date:** 2026-07-22
- **Phase:** U7.5A (Authority-and-Admission acceptance)
- **Related:** ADR-0033 through ADR-0037

## Context

U7.4 established deterministic Operation Admission and immutable decision evidence, but exposed
no operator transport or combined Authority-Admission read model. The Solo Alpha operator needs a
bounded way to submit proposals, observe persisted decisions, and audit genuine Authority links
without introducing an execution path or weakening the pure Admission domain.

## Decision

Add a trusted-local JSON API under `/api/admission/*`. It accepts a closed proposal DTO while the
server derives owner, actor, evaluation time, policy version, record identity, and all disposition
metadata. Mutation requires a direct `127.0.0.1` peer, strict bounded `application/json`, no
permissive CORS, and a narrow Origin/Sec-Fetch-Site defense. This remains a single-user local
boundary and is not a new authentication system.

The dependency direction is:

`API router -> Admission lifecycle/evidence orchestration -> domain repositories`.

The Admission domain remains the same three-file Authority-free package. Combined projections live
in `orchestration/admission_evidence.py`; the Admission repository reads only Admission rows, and
the Authority lifecycle reads Authority rows. Orchestration composes them without cross-domain
repository joins or new persisted records.

The Admission repository returns an authoritative `AdmissionWriteResult` with exactly `created` or
`replayed`. The API maps these to HTTP 201 and 200; conflicting reuse remains HTTP 409. No timestamp,
identifier, count, preflight read, second read, or response comparison infers the disposition.

Two owner-scoped read projections are exposed:

- admission-centric evidence always returns the Admission when present and carries `authority =
  null` when no grant was resolved; otherwise it contains only the genuinely linked grant chain;
- request-centric evidence returns the real Authority request chain and a deterministic bounded
  page containing only Admissions linked through grants issued from that request.

Both are read-only evidence projections. Neither claims completeness, authorization to execute, nor
proof that an operation ran.

## Alternatives considered

- **Put combined models in `orbitmind.admission`.** Rejected because the pure domain must not import
  Authority and its file inventory is architecture-pinned.
- **Construct repositories in the API.** Rejected because transport must not own domain composition
  or persistence boundaries.
- **Infer created versus replayed in the router.** Rejected because only the append repository owns
  the race-safe fact.
- **Add a Workbench mutation form for Admission.** Rejected for this slice; the existing Authority
  Workbench is browser-accepted and Admission uses a documented strict local JSON procedure.
- **Treat an admitted record as a capability or receipt.** Rejected: Admission is decision evidence
  only, and the Controlled Tool Gateway remains a later separately approved component.

## Consequences

- No migration, dependency, lockfile, or CI change is required; Alembic remains at `a1f4c7e9b230`.
- Replay returns the original immutable record without policy re-evaluation or mutation.
- Cross-owner reads are indistinguishable from absent records.
- PostgreSQL acceptance remains mandatory on the exact candidate head; local absence of a disposable
  PostgreSQL URL is recorded as environment-blocked, not product-passed.
- Operation execution, run-once enforcement, tools, command/tool results, providers, agents,
  worktrees, deployment, external communication, spending, hardware, and cloud quantum remain out
  of scope.

## Review trigger

Revisit only when a separately approved Controlled Tool Gateway needs an evidence-consumption
contract, when remote/multi-user authentication is designed, or when projection pagination must
advance beyond the bounded first-page contract.
