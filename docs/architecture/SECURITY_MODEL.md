# Security Model — OrbitMind Living Q-Core

Phase 0/1 is a local, single-user, single-tenant service with no network egress.
The model below states what is enforced now and what is designed for later.

## Authentication & authorization
- **Now:** none required (local single-user). All endpoints are unauthenticated
  on localhost.
- **Later:** API-key/OAuth at the `api` boundary; RBAC via the `identity` module;
  tenant isolation via a `tenant_id` column + row-level policy (Phase 8).
- Interfaces are designed so auth can be inserted as FastAPI dependencies without
  touching domain logic.

## Tenant isolation
Single-tenant now. Domain/persistence carry no tenant assumptions that would block
adding a `tenant_id` discriminator later (NFR-17).

## Secrets
- No secrets in code, logs, or VCS. `.env` is gitignored; `.env.example` holds no
  values (SR-15). Config is read only by `core.config`.

## Input hardening (untrusted HTTP input)
- Pydantic validation + domain validators on every request.
- Bounded propagation (max hours, step range, max samples) prevents resource
  exhaustion (SR-20).
- Unsupported satellite ids / output types are rejected, not guessed (SR-21).

## Filesystem / path-traversal
- Artifacts are written only under the configured artifacts dir. The mission id is
  a validated UUID; the resolved artifact path is checked to be inside the
  artifacts root or the write is rejected (SR-13/14).

## Code-execution safety
- No `eval`/`exec`/`pickle`-on-untrusted-input, no subprocess of user input, no
  execution of user-supplied files (SR-10/11). Generated-tool execution is not
  implemented; when it is, it follows lab→quarantine→…→approval→live (SR-09).

## Network & supply chain
- No outbound network in Phase 0/1 (SR-12). Tests assert offline behavior.
- Dependencies are constrained in `pyproject.toml` and installed with
  `--only-binary` to avoid source-build surprises. Dependency review + secret
  scanning are planned via GitHub Actions (see `.github/workflows/ci.yml` and
  ROADMAP Phase 8).

## Prompt injection / unsafe tool calls
- No LLM is on the orbital mission path (SR-01), so prompt injection has no
  numeric blast radius in Phase 1. When LLM-driven orchestration is added, mission
  text is treated as untrusted data, tools are allowlisted, and numeric work stays
  in deterministic tools.

## Error handling
- Centralized exception handlers return safe messages (no stack traces/paths/env)
  to clients; full detail goes only to structured server logs (SR-17).

## Incident response, backup, rollback (local posture)
- Git history provides rollback of code/docs. The SQLite DB and artifacts are
  reproducible from inputs; no production data exists yet. Formal DR is a Phase 8
  concern (PostgreSQL backups, object-storage versioning).
