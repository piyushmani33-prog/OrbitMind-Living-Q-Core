# U5.1 Camera Studio Ephemeral Alpha Closeout

Status: closeout record for the uncommitted Camera Studio ephemeral alpha.

## Identity And Scope

- Branch: `feature/u5-1a-local-camera-creation-studio`
- Base and HEAD: `a0c0be9009ff61880306946b381230a7ac665e4c`
- Scope: explicit browser-local still capture, a bounded temporary backend media
  session, and inert creation-goal proposal at `/workbench/camera`.
- Repository state: intentionally unstaged, uncommitted, unpushed, and not submitted
  as a pull request.

The final alpha scope is narrower than the earlier architectural records that describe
future save, provenance, persistence, model, and physical-validation possibilities.
Those capabilities are not part of this implementation.

## Slice Chronology

| Slice | Outcome | Closeout relevance |
| --- | --- | --- |
| U5.1A | Architecture review | Established local-first, explicit camera authority and non-goals. |
| U5.1B | Completed | Added immutable camera-session and frame-fact contracts. |
| U5.1C | Completed | Added the initially inactive browser preview sandbox. |
| U5.1D | Completed | Added one browser-memory still capture and cleanup behavior. |
| U5.1E0 | Completed | Made Pillow a reviewed direct decoder dependency. |
| U5.1E1 | Architecture review | Defined CSRF and injected runtime-root boundaries. |
| U5.1E2 | Completed | Implemented the camera-page CSRF and runtime foundation. |
| U5.1E-R | Blocked diagnostic | A full-suite failure led to the lifecycle investigation. |
| U5.1E-R1 | Blocked diagnostic | The original compact failure log was insufficient to name affected tests. |
| U5.1E-R1D | Completed diagnostic | Captured five authoritative lifecycle failures. |
| U5.1E-R2 | Completed | Corrected container ownership and media-service lifecycle handling. |
| U5.1F | Completed | Added explicit raw-Blob submission and discard. |
| U5.1G | Blocked diagnostic | Proposal request ordering did not satisfy the approved security order. |
| U5.1G1 | Blocked diagnostic | Preserved the security-order finding for its corrective gate. |
| U5.1G2 | Completed | Added non-mutating protocol preflight before proposal body handling. |
| U5.1G3 | Completed | Isolated create, discard, and proposal CSRF route scopes. |

The blocked entries remain historical findings. They are not presented as implementation
completion: U5.1E-R1D/U5.1E-R2 supplied the lifecycle correction, and U5.1G2/U5.1G3
supplied the proposal security corrections.

## Final Architecture

Pure camera contracts are framework-free. Camera runtime context supplies the exact
temporary-root child, UTC clock, randomness, and process-binding key. The API
composition root owns the media service and page-CSRF registry when it creates a
container; an explicitly caller-owned container survives a borrowed application
lifespan. Owned shutdown closes media before the CSRF registry and remains idempotent.

The alpha adds no persistence model, database table, migration, media retrieval route,
model/agent integration, external provider, or quantum dependency. Pillow appears
once as the direct bounded JPEG/PNG decoder declaration, and the approved Windows lock
remains unchanged.

## Final User Workflow

1. `/workbench/camera` loads inactive.
2. The user explicitly enables camera permission and sees an active local preview.
3. The user explicitly captures one still. Capture stops camera tracks.
4. The still remains in browser memory until Retake, local Discard, or an explicit
   temporary-session submission.
5. The user explicitly creates a temporary server session from the raw JPEG/PNG Blob.
6. The user selects one bounded creation goal and may provide bounded inert context.
7. The user explicitly creates one inert temporary proposal.
8. The user may explicitly discard the parent frame and attached proposal. Otherwise,
   both expire after 15 minutes.

There is no automatic permission request, capture, upload, proposal, retry, polling,
media download, media retrieval, permanent save, image analysis, or proposal
execution.

## Contracts And Security Boundaries

- Capture accepts JPEG or PNG only, limits output to 1920 by 1080 pixels and
  5,000,000 bytes, and uses JPEG quality 0.90.
- Backend intake streams a bounded raw body, checks Content-Length, validates declared
  and decoded media agreement, rejects decompression-bomb conditions, freshly encodes
  the accepted raster, and derives authoritative facts from normalized bytes.
- Temporary files use generated names, containment checks, an atomic `.part` then
  replace sequence, digest-only capability storage, and publication only after final
  replacement.
- The media service limits itself to eight active sessions and 40,000,000 normalized
  bytes. It performs startup, lazy-expiry, discard, and shutdown cleanup.
- `GET /workbench/camera/api/sessions/{session_id}` is capability-scoped metadata
  status only. No route returns camera image bytes.
- Camera CSRF requires exact loopback Host and Origin values, same-origin Fetch
  Metadata, an HttpOnly SameSite=Strict page cookie, and the current private token.
  Token digests are stored server-side and comparison is constant time.
- CSRF authority has a 900-second absolute lifetime, rotates atomically after accepted
  authority, rejects replay, fails closed on lost responses, invalidates BFCache pages,
  and is invalidated by application restart.
- Proposal protocol preflight is non-mutating. Host, Origin, and Fetch Metadata are
  checked before declared proposal size and body handling. The exact scopes are
  `CREATE_SESSION`, `DISCARD_SESSION`, and `CREATE_PROPOSAL`; a proof for one scope
  cannot authorize another.
- Media capability and CSRF authority are independent. Both are required where the
  modifying route needs both permissions.

## Proposal Semantics And Privacy

The five goals are `visual_reference`, `documentation`, `transformation_request`,
`explanation_request`, and `other`. Context is optional inert normalized text up to
500 code points, except `other` requires non-empty context. Proposal requests are
strict JSON with a 4,096-byte limit.

A proposal is one `proposal_only` in-memory attachment to its parent session. It has a
separate 256-bit identifier, expires with its parent, and is removed with the parent.
It uses only stored frame facts. It does not open image files, read image bytes, invoke
Pillow, construct a prompt, invoke a model or agent, analyze content, or execute any
action. Human approval remains required for any future use.

The alpha avoids plaintext server-side CSRF tokens, plaintext media capabilities,
original filenames, retained device labels, browser media storage, internal media
paths, image bytes in logs, proposal context in logs, media capabilities in the DOM,
authority in URLs, and secrets in query strings. It performs no biometric processing,
facial recognition, OCR, person identification, object classification, scene
interpretation, surveillance, telemetry, or external AI call.

## Validation

The closeout focused camera regression set passed `338 passed, 1 warning`. Ruff format
and lint passed. Linux-platform, Windows-platform, and normal mypy each passed.

The single final standard source-suite invocation passed `1852 passed, 262 skipped,
3 warnings in 2037.50s (0:33:57)`. The skipped tests are the established optional
quantum cases in an environment without Qiskit/Aer. The closeout runner recorded one
pytest child, exit code zero, and no retry.

## Known Limitations

- No physical-camera hardware validation was performed. Automated browser coverage
  uses mocked media APIs.
- No authenticated user accounts, durable ownership model, permanent media save, or
  proposal persistence exists.
- File deletion remains best effort when an operating system prevents removal.
- No security certification, public release, deployment, installer refresh, or frozen
  candidate refresh is implied by this closeout.

## Deferred Work

The following remain outside this ephemeral alpha and are not approved by this report:

- physical-camera manual validation;
- durable media save and provenance-backed permanent artifacts;
- proposal persistence;
- model or agent image processing, OCR, image transformation, and explanation
  generation;
- face or biometric processing;
- external AI and cloud media;
- sharing, publishing, deployment, and public release;
- background recording, multi-frame capture, and video;
- installer or frozen-candidate refresh.

## Closeout Decision

READY FOR U5.1 CAMERA STUDIO COMMIT AND PR PREPARATION APPROVAL, subject to the
external evidence and repository-integrity review recorded by this closeout gate.
