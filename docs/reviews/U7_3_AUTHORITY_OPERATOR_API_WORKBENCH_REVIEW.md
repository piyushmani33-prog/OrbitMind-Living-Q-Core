# U7.3 Authority Operator API and Approval Workbench - Review

## Scope

U7.3 adds a local evidence interface over the existing U7.0/U7.1/U7.2 Authority
chain. It includes strict owner-scoped JSON transport, a server-rendered
Approval Workbench, a shared process-local page-CSRF primitive, and bounded
read projections. It does not add production authentication, remote access,
operation admission, tool invocation, agent execution, a runtime enforcement
path, a credential, a migration, a dependency, or a lockfile change.

## Boundary findings addressed

- **Trusted-local owner and actor:** one explicit trusted-local context supplies
  both. Request bodies and forms cannot override owner or actor attribution.
  Every Authority route independently requires a direct `127.0.0.1` peer.
  This is intentionally not a production authentication claim.
- **Shared CSRF:** `AppContainer` owns one process key and one core registry for
  static Camera and Authority scopes. The Camera compatibility facade delegates
  to it. Authority has no separate secret, registry, or port setting.
- **Same-origin form policy:** each Authority POST requires the exact
  runtime-selected loopback origin, a single cookie/token pair, same-origin
  fetch metadata, no forwarded headers, an explicit confirmation, and a
  form-url-encoded bounded body. Protocol preflight happens before body
  consumption. Tokens rotate after success and never occur in URLs or logs.
- **Service boundary:** the router does not import or construct
  `SqlAlchemyAuthorityRepository`; lifecycle services retain repository and
  transaction ownership. Typed lifecycle errors are mapped in API/HTML
  transport, not in orchestration.
- **Evidence reads:** exact-grant revocation/evaluation queries are database
  filtered and bounded; grant projections use an exact revocation aggregate and
  one-row latest-evaluation read; list projections use a bounded probe row for
  truthful truncation; post-cap record replays use exact owner- and grant-scoped
  reads; request-chain construction rejects oversized evidence.
- **No execution:** the Workbench has no execute/run/invoke action. Requests,
  approvals, grants, revocations, and evaluations remain append-only evidence;
  no operation admission or execution receipt exists.

## Candidate-scope audit

The R5 authoritative rebaseline accepts exactly 16 changed repository paths:
nine production Python paths, four test paths, and three documentation paths.
The original eight-production-file cap is superseded for this branch by the
approved nine-file amendment; it does not authorize a tenth production path.
There are no migration, dependency, lockfile, or CI-workflow changes.

The nine production Python paths are:

1. `src/orbitmind/api/app.py`
2. `src/orbitmind/api/container.py`
3. `src/orbitmind/api/authority_schemas.py`
4. `src/orbitmind/api/presentation/authority.py`
5. `src/orbitmind/api/routers/authority.py`
6. `src/orbitmind/camera/csrf.py`
7. `src/orbitmind/core/page_csrf.py`
8. `src/orbitmind/orchestration/authority_lifecycle.py`
9. `src/orbitmind/persistence/authority_repository.py`

`src/orbitmind/core/config.py` has no U7.3 diff, and the interrupted
Authority-only CSRF module was removed before the final patch. No security code
is hidden in the router to satisfy the cap.

## Fresh R5 validation status

Fresh R5 focused validation passed without failures or errors:

- Authority JSON API: 12 passed.
- Approval Workbench: 15 passed.
- Authority contracts, persistence, lifecycle transactions, inherited
  semantics, and architecture boundaries: 119 passed.
- Shared Camera page-CSRF compatibility: 132 passed.
- PostgreSQL-marked Authority API: 3 skipped because
  ORBITMIND_TEST_POSTGRES_URL is not configured. PostgreSQL remains mandatory
  in exact-head CI with a disposable migrated database.

Static validation also passed: Ruff format check reported 416 files already
formatted; Ruff lint passed; strict mypy passed on Linux, Windows, and the
default platform for 236 source files; Alembic reported the sole approved head
9313833e1f07; and git diff --check passed apart from known CRLF-normalization
warnings.

Browser-CSRF validation remains pending. Independent review remains pending.
The complete source suite remains pending. This candidate adds no runtime
enforcement or operation execution and has not been staged, committed, pushed,
or proposed for review. It does not claim U7.3 completion, a merge, release,
or production authorization.
