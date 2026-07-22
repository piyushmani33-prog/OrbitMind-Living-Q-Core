# U7.5A Authority-Admission Acceptance - Review

## Epistemic status

`governance.epistemic: implementation-evidence`

This document describes the reviewable implementation candidate. Exact command transcripts,
environment classifications, JUnit counts, and artifact hashes are sealed outside the repository;
fresh independent review and exact-head PostgreSQL CI remain separate gates.

## Scope

U7.5A adds a narrow trusted-local Admission JSON API, authoritative create/replay disposition, and
read-only Authority-Admission evidence projections. It validates the existing Authority Workbench
as the browser-visible portion of the operator journey and uses controlled service/dependency probes
for scenarios a normal request body must not express.

The candidate changes exactly 17 paths: six production Python paths, eight test paths, and three
documentation paths. It adds no migration, dependency, lockfile, or CI change. Alembic remains at
`a1f4c7e9b230`.

## Boundary findings addressed

- **Trusted fields:** owner, actor, evaluation time, policy version, Authority resolution, ids,
  checksums, identity, timestamps, and disposition are server/repository owned. `requested_at` is
  audit-only.
- **Trusted transport:** mutation requires direct IPv4 loopback, strict bounded JSON, no permissive
  CORS, and narrow Origin/Fetch-Metadata checks. Reads and writes are bounded and owner-scoped;
  foreign-owner misses are public-safe not-found responses.
- **Repository disposition:** the append repository returns `created` or `replayed` at the exact
  race-safe decision point. The API maps these to 201/200; conflicting reuse maps to 409. Replays
  neither re-evaluate policy nor mutate stored evidence.
- **Domain purity:** the Admission domain remains Authority-free and file-pinned. The API imports
  only Admission contracts, while orchestration owns combined evidence composition. The Admission
  repository performs no Authority join.
- **Truthful projections:** admission-centric reads preserve null Authority linkage. Request-centric
  reads include only records linked through grants from the requested chain, in deterministic
  bounded order with a truthful `truncated` signal.
- **Acceptance classes:** A covers normal operator-visible Authority Workbench and Admission JSON
  journeys; B covers controlled actor mismatch, clock expiry, revocation, replay/conflict, restart,
  and tamper probes; C covers transport, owner-isolation, profile/capability/scope, determinism, and
  fail-closed integrity; D (all execution) is explicitly deferred.

## Non-execution result

Admission persists decision evidence only. The candidate adds no arbitrary command, subprocess,
shell, tool adapter, worktree operation, provider/external-AI call, external communication,
deployment, spend, hardware action, cloud-quantum execution, agent runtime, run-once mechanism,
execution receipt, command result, or tool result. Trusted loopback HTTP, deterministic policy and
Authority evaluation, owner-scoped database access, browser rendering, and external validation
evidence are the only permitted effects.

## Review boundary

An admitted response is not permission to execute, a bearer capability, an execution token, or proof
that an operation ran. U7.5A does not begin the Controlled Tool Gateway or any later Agent Execution
Spine component. The candidate is not merged, deployed, released, or production-authorized by this
document.
