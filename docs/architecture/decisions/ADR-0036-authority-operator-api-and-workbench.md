# ADR-0036 - Authority Operator API and Approval Workbench (U7.3)

- **Status:** Accepted (2026-07-19)

## Context

U7.0 established pure Authority contracts, U7.1 added append-only owner-scoped
evidence persistence, and U7.2 introduced the lifecycle service boundary.
Operators need a local evidence interface, but a request, approval, grant, or
evaluation must not become operation admission or execution authority. The
existing Camera Workbench has a mature local page-CSRF contract; introducing
another independent CSRF registry or process secret would duplicate
security-sensitive behavior and split lifecycle ownership.

## Decision

Add a local-only Authority JSON API and server-rendered Approval Workbench.

1. The router remains HTTP transport only. It receives the owner and fixed
   local operator actor from one trusted-local context, parses strict input,
   delegates all Authority reads and mutations to U7.2 lifecycle services, and
   maps typed lifecycle errors to HTTP. It never constructs an Authority
   repository or owns a repository transaction. Every Authority route requires
   a direct `127.0.0.1` peer; this local transport guard does not claim to be
   production authentication.
2. The Workbench exposes only explicit POST/Redirect/GET evidence actions:
   create request, record terminal decision, issue grant, append revocation,
   and persist grant-backed evaluation. Each form requires an explicit
   confirmation. GET handlers make no durable mutation.
3. Put the reusable page-CSRF primitive in `orbitmind.core.page_csrf`.
   `AppContainer` owns one process binding key and one registry. Static Camera
   and Authority policies share that registry; the Camera facade preserves its
   existing interface. Authority owns neither a second registry nor a secret.
4. Require exact same-origin Authority form posts using the runtime-selected
   loopback port, one Authority cookie namespace, `HttpOnly`/`SameSite=Strict`
   cookie flags, token rotation, expiry, bounded storage, and constant-time
   digest comparison. Forwarded headers, token ambiguity, scope mismatch, and
   non-exact origin inputs fail closed before form-body consumption.
5. Preserve lifecycle purity: no HTTP status belongs in orchestration.
   API and HTML transport surfaces map the typed immutable terminal-decision
   conflict to HTTP 409.
6. Bound exact-grant revocation/evaluation reads in the repository and bound
   complete request-chain assembly in lifecycle services. Use a one-row page
   probe for truthful truncation, an exact revocation aggregate, and a one-row
   latest-evaluation read for grant projections.

The trusted-local context is not production authentication, multi-user
authorization, a remote identity claim, or a future operation-admission
mechanism. It is the explicit replacement point for a later reviewed
authentication boundary.

## Alternatives considered

- **Authority-specific CSRF registry and secret**: rejected because duplicate
  process-local security state can diverge from Camera behavior.
- **Place shared CSRF under `api`**: rejected because Camera would back-import
  the API layer. The pure core primitive preserves module direction.
- **Router-side repository construction or transaction**: rejected because it
  bypasses lifecycle validation and transaction ownership.
- **Fixed Authority port**: rejected because runtime already selects the local
  loopback port; a second configuration source would drift.
- **Execution or operation-admission control**: rejected as out of scope. U7.3
  records and projects evidence only.

## Consequences

The API layer is now a reviewed Authority consumer, while the pure Authority
domain remains dependency-closed. The operator interface has no network
provider, tool, agent, browser-side storage, credential, runtime enforcement,
or execution receipt surface. SQLite remains available for offline tests;
PostgreSQL-marked tests exercise the same API over the migrated schema when a
disposable database is supplied. The Alembic head remains `9313833e1f07`.

The U7.3 implementation is constrained to nine changed production Python paths
and adds no migration, dependency, lock, or configuration-port field.

## Review trigger

Revisit before adding production authentication, multi-user tenancy, remote
operator access, operation admission, tool invocation, execution receipts, or
any additional page-CSRF policy. Those changes require a dedicated threat model
and a separate decision record.
