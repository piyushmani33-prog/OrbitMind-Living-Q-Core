# Local Camera Creation Studio

Status: architecture approved for review; no camera implementation is authorized by
this document.

## Purpose

Camera Creation Studio is a user-controlled, local visual-input surface that converts
one explicitly captured still frame into a reviewable creation proposal. The frame is
evidence supplied by the user, not permission for OrbitMind or an agent to act.

The first version supports a local browser preview, one still capture, one selected
creation goal, optional user context, and a draft proposal. Capture never causes an
automatic save, tool call, external disclosure, publication, or real-world action.

This design preserves OrbitMind's system spine:

`User intent -> bounded intake and validation -> creation proposal -> evidence and
provenance -> reviewable output -> explicit human approval -> optional later task`

## User Stories

- As a user, I can open `/workbench/camera` without the browser requesting camera
  permission.
- As a user, I can explicitly enable one local camera and see an unmistakable active
  state.
- As a user, I can capture one still frame and know that camera tracks stop immediately
  afterward.
- As a user, I can retake or discard the frame before any backend receives it.
- As a user, I can choose one bounded creation goal and add optional context.
- As a user, I can review and edit a draft before deciding whether to save it.
- As a user, I can see whether the frame is ephemeral, saved, deleted, or awaiting
  deletion.
- As a user, I can inspect provenance and uncertainty without model interpretation
  being presented as fact.

## Non-Goals

Camera Creation Studio is not:

- surveillance, continuous observation, or background monitoring;
- autonomous vision or a security-camera product;
- video or audio recording;
- microphone access;
- face or identity recognition;
- biometric processing, emotion detection, or sensitive-trait inference;
- medical diagnosis;
- remote camera access or media streaming;
- autonomous publication, execution, deployment, purchase, messaging, or equipment
  control;
- a permission surface an agent may operate;
- a connected external-AI feature;
- a replacement for human consent when another person may be captured.

## Governing Principles

1. The user is the sole camera authority.
2. Camera access begins only after an explicit user gesture.
3. One capture produces one still frame; no sampling loop exists.
4. Camera tracks stop after capture by default and on every terminal or error path.
5. Browser memory is the first and preferred frame location.
6. Backend transfer requires a second explicit action: `Create proposal` or `Save`.
7. Persistence requires an explicit `Save` decision.
8. Agents consume validated contracts, never camera, browser, or filesystem handles.
9. Image content is untrusted evidence and cannot grant authority.
10. External processing is prohibited until a separately approved connected-processing
    gate.

## First-Version User Flow

1. The user opens `/workbench/camera`.
2. The initial page is inactive. It shows a privacy explanation, no preview, no stored
   frame, and makes no permission request.
3. The user clicks `Enable camera`.
4. The browser performs its own permission prompt.
5. On approval, the page shows the local preview, a visible `CAMERA ACTIVE` indicator,
   a sanitized camera label, `Capture frame`, and a large `Stop camera` control. No
   recording begins.
6. The user clicks `Capture frame`.
7. The controller captures one still frame and immediately stops every media track.
8. The page shows the captured frame in browser memory with `Retake` and `Discard`.
9. `Retake` is a new explicit user action. It may restart camera access but never does
   so automatically.
10. The user selects exactly one creation goal and may add optional bounded context.
11. The user clicks `Create proposal`. Only now may the validated frame be sent to a
    backend ephemeral session.
12. OrbitMind returns a draft proposal. The user may edit, discard, or explicitly save
    it.
13. Any later agent task is a separate bounded proposal requiring explicit approval.

Navigation, `pagehide`, page closure, capture, stop, discard, error, expiry, and
shutdown all invoke idempotent cleanup.

## Permission Authority

- `navigator.mediaDevices.getUserMedia` may be called only from the reviewed camera
  controller in response to `Enable camera` or an explicit `Retake` action.
- Page load, agent output, API response, timers, restored state, and navigation may not
  trigger permission.
- Permission is not assumed to persist. Each start checks the current browser result.
- Denial, no device, device busy, disconnect, and generic startup failures are
  sanitized and fail closed.
- One page owns at most one active media stream.
- `Stop camera` remains visible and keyboard-accessible whenever a track is active.
- All tracks are stopped explicitly; dropping a DOM reference is not sufficient.
- No hidden iframe, third-party script, CDN, analytics, WebRTC peer connection,
  external media server, or network stream is permitted.
- The camera selector is shown only when the browser safely exposes choices. Labels
  are bounded and sanitized; hardware serials and full device identifiers are not
  retained.

## Media Scope and Limits

The first version supports only local live preview and one captured still image.

| Property | Contract |
| --- | --- |
| Media types | JPEG or PNG after decode validation |
| Maximum dimensions | 1920 x 1080 pixels |
| Maximum encoded size | 5 MB (5,000,000 bytes) |
| Images per request | One |
| Orientation | Normalize before approved persistence where practical |
| Metadata | Remove ancillary metadata before approved persistence where practical |
| Filename | Backend generated; never a client path or original filename |

The browser may resize and encode the capture for responsiveness, but the backend
must independently validate type, magic bytes, decoded dimensions, decoded pixel
budget, and final size. Client validation is usability, not authority.

The first version does not support audio, video recording, continuous frame analysis,
sampling loops, motion detection, face detection, face recognition, emotion
inference, biometric templates, autonomous OCR, automatic QR/barcode actions, camera
pan/tilt/zoom, remote cameras, or simultaneous multi-camera capture.

## Lifecycle

Each transition produces a new immutable session snapshot. The server is authoritative
after backend session creation.

| State | Meaning | Permitted next states |
| --- | --- | --- |
| `inactive` | Page loaded; no camera or frame | `permission_pending`, `discarded` |
| `permission_pending` | Explicit start is awaiting browser result | `preview_active`, `failed`, `discarded` |
| `preview_active` | Visible local preview; tracks active | `frame_captured_ephemeral`, `inactive`, `failed`, `discarded` |
| `frame_captured_ephemeral` | One frame exists in browser memory; tracks stopped | `permission_pending`, `proposal_pending`, `discarded`, `expired`, `failed` |
| `proposal_pending` | Frame was explicitly submitted to bounded temporary processing | `proposal_ready`, `discarded`, `expired`, `failed` |
| `proposal_ready` | Reviewable draft exists; no automatic action | `saved`, `discarded`, `expired`, `failed` |
| `saved` | User approved persistence and provenance was committed | terminal except explicit later delete workflow |
| `discarded` | User discarded frame/session/proposal | terminal |
| `expired` | Bounded lifetime ended and cleanup was attempted | terminal |
| `failed` | Sanitized fail-closed outcome and cleanup was attempted | terminal |

Rules:

- Preview frames are never persisted.
- A captured frame begins in browser memory only.
- The backend receives a frame only after explicit `Create proposal` or `Save` action.
- Backend temporary media expires after 15 minutes.
- Completion, discard, expiry, failure, and shutdown cleanup remove temporary media.
- Persistence requires explicit `Save`.
- No raw camera stream is stored.
- Abandoned sessions expire deterministically, including after restart.
- Object URLs are revoked, canvas buffers are cleared, and media elements are reset.
- Deletion failures are recorded as `deletion_failed`; the UI must not claim deletion
  succeeded when it did not.

## Creation Session Contract

The domain contract is immutable, versioned, and UTC-aware. It contains:

- `session_id`: backend-generated opaque identifier;
- `owner_id`: trusted dependency value where authentication/ownership exists;
- `state`;
- `creation_goal`;
- `created_at` and `expires_at` as timezone-aware UTC values;
- `media_type`, `width`, `height`, and `encoded_size` from backend validation;
- `content_checksum` as SHA-256 of the normalized accepted frame;
- `capture_source = local_camera`;
- `sanitized_device_label`;
- `permission_result` from a fixed vocabulary;
- `frame_persisted`;
- `proposal_id`;
- `user_approval_status`;
- `retention_status`;
- `deletion_status`;
- `failure_code` from the stable error model;
- `schema_version` and transition timestamp for replayable evidence.

The contract never stores camera hardware serial numbers, complete device identifiers,
IP addresses, browser history, biometric templates, inferred identity, emotion, race
or ethnicity, gender, medical status, unrelated machine metadata, original client
filenames, or client-provided filesystem paths.

## Creation Goals and Output Contracts

### Scene or object description

- observable items;
- spatial relationships;
- explicit uncertainty;
- questions requiring user confirmation.

### Idea or project brief

- observed input;
- problem and concept;
- goals and possible components;
- constraints and safety considerations;
- open questions;
- proposed next task, still requiring approval.

### Experiment observation

- visible setup and visible state;
- capture time and user notes;
- hypothesis and proposed measurements;
- an explicit statement that no scientific validation is claimed.

### Development task

- visual problem statement;
- desired outcome;
- proposed acceptance criteria;
- frame checksum as evidence linkage;
- approval requirement.

### Research question

- observed subject;
- questions and assumptions;
- evidence required;
- safe research plan.

Every output is a draft proposal. OrbitMind currently has no approved local semantic
vision component. Until one is separately selected, the proposal workflow may only
structure user-provided context and frame metadata; it may not claim to have
interpreted pixels. Selection, packaging, performance, licensing, and evaluation of a
local vision model are deferred to U5.1F or a narrower prerequisite gate.

## Agent Authority Boundary

Camera-derived agents may describe non-sensitive objects using approved processing,
organize user ideas, propose briefs/experiments/development tasks/research questions,
identify uncertainty, ask clarifying questions, and draft documents.

They may not activate or reopen the camera, capture an image, continuously watch,
identify a person, infer sensitive characteristics, execute code from image content,
open image URLs, install software, purchase, message, publish, operate equipment,
deploy, or create an external real-world action.

Every downstream task requires the explicit capture event, selected goal, bounded
scope, frame checksum, provenance, expiry, and a separate explicit user approval.
Agents receive immutable service contracts. They never receive browser media streams,
camera device objects, temporary paths, or unrestricted filesystem handles.

## External-AI Boundary

The first version is local-only by default. No frame may be sent to ChatGPT, Claude,
Gemini, Copilot, another external API, or a remote vision model.

Any future connected-processing gate must use per-request consent that displays the
exact image, destination, disclosure reason, provider retention policy and terms,
redaction option, cancel option, and audit record. Broad or permanent consent is not
acceptable. Cancel must occur before bytes leave the local process.

## Provenance and Epistemic Labels

Every saved camera-derived artifact records:

- user-triggered local capture and capture time;
- frame and output checksums;
- selected creation goal;
- local or external processing status;
- exact processing components and model/agent identity, if any;
- user context and edits;
- approval state;
- retention and deletion status;
- evidence links from proposal to the accepted frame.

Output fields use explicit labels: `visual observation`, `user-supplied context`,
`model interpretation`, `inferred`, `uncertain`, and `not independently verified`.
Generated interpretation is never `verified-fact`. Deterministic metadata such as
checksum or dimensions is labeled separately from semantic interpretation.

## Human-Subject and Privacy Rules

- The page warns that people may appear and that the user is responsible for consent.
- `CAMERA ACTIVE` is visible and announced; covert capture is prohibited.
- Face recognition, identity matching, biometric templates, sensitive-trait
  inference, emotion analysis, and minor-focused profiling are prohibited.
- When people appear, output is limited to neutral, non-identifying scene description
  needed for the selected goal.
- The user always has immediate frame/proposal discard and an explicit retention
  choice.
- Logs and errors omit device identifiers, raw media, paths, and person-derived
  details.

## Visual Prompt-Injection Boundary

Text, QR codes, screens, printed instructions, signs, and displayed prompts inside a
frame are untrusted visual content. Extracted text, if a later approved component
produces it, is quoted evidence rather than instruction.

Image content cannot change policy, grant permission, approve itself, trigger tools,
execute commands, open URLs, install packages, delete files, communicate externally,
purchase, deploy, or control hardware. The proposal service accepts a fixed creation
goal and emits a data-only draft. Tool-capable agents require a separate approved task
whose authority is independent of image text.

## Browser Security Design

### Current baseline

OrbitMind currently serves `/workbench` and its POST routes from a FastAPI router with
server-rendered HTML and inline CSS. One reviewed controller is served at the exact
same-origin `/assets/trajectory-replay.js` route from package resources. There is no
generic static mount or template engine.

The current CSP is deny-by-default. It allows same-origin external scripts, inline
styles, same-origin/data images, and same-origin form actions while denying browser
connections, workers, objects, media, and manifests. Current `Permissions-Policy`
sets both `camera=()` and `microphone=()`.

### Future camera-page policy

- `/workbench/camera` fits the existing Workbench HTML subtree, but should be owned by
  a separate narrow camera router/controller rather than enlarging the mission router.
- The camera page must receive route-specific `Permissions-Policy: camera=(self)` (or
  a verified narrower equivalent). All other pages retain `camera=()`.
- `microphone=()` remains global and route-specific.
- The controller is a reviewed same-origin package asset. No inline executable script,
  `eval`, external script, iframe, CDN, analytics, or dynamic code loader is allowed.
- The current `script-src 'self'`, `connect-src 'none'`, `object-src 'none'`,
  `frame-ancestors 'none'`, and `form-action 'self'` restrictions remain.
- The camera page must test whether `video.srcObject = stream` works under the current
  `media-src 'none'`. If a browser requires a media allowance for a local MediaStream,
  use a page-specific minimum such as `media-src 'self' blob:` only after CSP tests;
  do not relax other pages.
- HTTP loopback origins such as `http://127.0.0.1` are treated as potentially
  trustworthy for secure-context checks in current browser security models. Physical
  browser verification remains mandatory because permission UX and device support
  are browser and OS dependent.
- `pagehide`, navigation, capture, stop, discard, and error handlers stop all tracks,
  revoke object URLs, clear canvas dimensions and buffers, and reset media elements.

### Request security

- State-changing camera endpoints require an exact same-origin `Origin`, accepted
  Fetch Metadata, and a session-bound CSRF token. Existing form-action CSP alone is
  not a CSRF defense.
- The body is streamed and rejected above 5 MB plus a small fixed protocol overhead;
  declared and observed lengths must agree when `Content-Length` is present.
- Submit one raw `image/jpeg` or `image/png` body to an opaque session endpoint rather
  than introducing multipart merely for one file. Session metadata uses bounded JSON.
- Validate content type, magic bytes, complete image decode, dimensions, pixel budget,
  and decompression-bomb limits. Re-encode before persistence.
- Generate backend filenames. Never accept a client path or serve an arbitrary path.
- Resolve every temporary and persistent path under its approved root.
- Derive owner authority from the trusted dependency, never request JSON.
- Status and media retrieval are owner-scoped and do not reveal whether another
  owner's identifier exists.

## Conceptual API Surface

These routes are architecture contracts, not implemented endpoints:

| Method and path | Purpose |
| --- | --- |
| `GET /workbench/camera` | Render inactive local camera page |
| `POST /api/v1/camera-sessions` | Create owner-bound ephemeral session |
| `PUT /api/v1/camera-sessions/{session_id}/frame` | Stream one bounded raw frame |
| `POST /api/v1/camera-sessions/{session_id}/proposal` | Request one bounded draft |
| `POST /api/v1/camera-sessions/{session_id}/save` | Explicitly persist approved result |
| `DELETE /api/v1/camera-sessions/{session_id}` | Discard and clean session |
| `GET /api/v1/camera-sessions/{session_id}` | Retrieve owner-scoped status |

Each mutation uses the current immutable state as a precondition so replayed or
out-of-order requests fail closed.

## Storage and Retention

Browser memory is authoritative until explicit submission. Backend temporary media is
stored beneath the runtime's approved `temp` root in a camera-specific directory with
generated identifiers, restrictive inherited ACLs, and a 15-minute expiry. It is not
served by a generic file route.

Approved saved images live beneath a dedicated camera-media area of the user-scoped
OrbitMind data/artifacts root. A generated or content-addressed identifier replaces
the original filename. Database metadata binds owner, checksum, media properties,
proposal, provenance, retention, and deletion state. Existing legacy mission-artifact
serving is path-safe but not an adequate camera owner boundary and must not be reused
unchanged.

Cleanup is idempotent and records attempted/completed/failed deletion. Startup and
shutdown run bounded expiry cleanup. A missing file does not erase its audit record;
a present file after a claimed deletion is a test failure.

## Persistence and Migration Assessment

No migration is needed for U5.1B through the browser-memory-only U5.1D slices.
Backend ephemeral sessions in U5.1E need durable restart-aware metadata or an
equivalent reviewed manifest design. Explicit save/provenance in U5.1G requires new
owner-scoped tables for camera sessions, media objects, proposals, retention/deletion
events, and provenance links. At least one Alembic migration is therefore expected
before backend persistence is enabled.

The exact table split, whether ephemeral metadata is database-backed, and whether a
saved frame is an artifact subtype are deferred. Binary image bytes remain on disk;
the database stores metadata, generated relative paths, checksums, and relationships.

## Dependency Assessment

- Browser-native MediaDevices, MediaStream, video, canvas, Blob, and object-URL APIs
  are sufficient for permission, preview, still capture, client bounds, and discard.
- The current server has bounded URL-encoded body readers and a streaming handoff
  reader, but no reusable binary upload service.
- `python-multipart` is not a current dependency. A raw binary frame endpoint avoids
  adding it for a one-file protocol.
- Pillow is present in the Windows lock as a Matplotlib transitive dependency, but is
  not declared as a direct OrbitMind dependency. Safe backend decode/re-encode and
  decompression-bomb defense should use a reviewed direct Pillow dependency rather
  than rely on transitive presence.
- OpenCV is unnecessary for browser capture and would add excessive package, native,
  and frozen-build scope.
- The Python standard library provides hashing, generated identifiers, atomic file
  replacement, UTC time, and bounded stream handling, but not a complete safe image
  decoder.
- No approved local semantic vision model exists. That decision is independent of
  capture and validation and belongs to U5.1F or a prerequisite review.

No dependency is added by this architecture gate.

## Error Model

| Code | Meaning and fail-closed behavior |
| --- | --- |
| `camera_not_supported` | MediaDevices unavailable; no permission request or state created |
| `camera_permission_denied` | Browser denied access; remain inactive |
| `camera_not_found` | No usable video input; remain inactive |
| `camera_in_use` | Device unavailable/busy; stop any partial tracks |
| `camera_disconnected` | Active track ended; stop all tracks and clear preview |
| `camera_start_failed` | Sanitized start failure; clear all camera state |
| `capture_failed` | No valid still produced; stop tracks and discard partial buffer |
| `image_too_large` | Encoded body exceeds limit; consume/reject safely and delete partial file |
| `image_dimensions_invalid` | Decoded dimensions/pixel budget invalid; delete temporary bytes |
| `image_type_invalid` | MIME/magic/decode mismatch; delete temporary bytes |
| `image_decode_failed` | Complete decode failed; delete temporary bytes |
| `temporary_storage_failed` | No proposal begins; remove partial media and record fixed failure |
| `session_expired` | Session is unavailable and cleanup is attempted |
| `proposal_failed` | Draft not produced; temporary retention follows bounded cleanup policy |
| `save_not_approved` | Save lacked explicit approval/current state; nothing persisted |
| `deletion_failed` | Do not claim deletion; retain sanitized audit status for retry/review |

Errors omit hardware serials, local paths, browser internals, raw media, request
bodies, and tracebacks. Every error stops active tracks and removes failed temporary
frames where possible.

## UI Specification

The minimal page contains:

- `Camera Creation Studio` heading;
- local-processing/privacy explanation and people-in-frame notice;
- inactive placeholder;
- `Enable camera`;
- camera selector when safely available;
- visible and announced `CAMERA ACTIVE` indicator;
- live preview;
- `Capture frame` and large `Stop camera` controls;
- captured-image preview with `Retake` and `Discard`;
- creation-goal selector and optional bounded context;
- `Create proposal`;
- proposal preview with `Edit`, `Save`, and `Discard proposal`;
- provenance summary and retention/deletion state.

Keyboard operation, visible focus, screen-reader labels, polite/assertive status
announcements as appropriate, non-color-only states, reduced-motion compatibility,
and mobile-width support are required. Controls hidden by state must not leave active
camera access without an available stop action.

## Architecture Boundaries

| Layer | Proposed responsibility |
| --- | --- |
| Frontend | Camera page/template, state controller, media-device adapter, frame encoder, preview/capture controller, explicit upload/save client |
| API | Render page; create/discard/status endpoints; one-frame intake; proposal/save commands; CSRF/origin/content limits |
| Application | `CameraSessionService`, `CameraFrameValidationService`, `CameraProposalService`, `CameraRetentionService`, `CameraProvenanceService` |
| Domain | Immutable states, creation-goal enum, errors, retention decision, proposal and provenance contracts |
| Infrastructure | Temporary media store, approved persistent media store, checksum service, image decoder/validator, expiry cleanup |

The dependency direction remains `api -> application/domain -> persistence/core`.
Domain code does not import the API. Agents consume application services and typed
contracts; they do not access camera APIs, browser streams, or filesystems.

## Threat Model

| Threat | Boundary | Mitigation | Failure behavior | Required test |
| --- | --- | --- | --- | --- |
| Covert capture | Browser permission/controller | Explicit gesture, visible active state, no auto-start | Stop tracks and remain inactive | No permission call on load; active indicator test |
| Retained media after discard | Browser and media stores | Clear buffers, delete temp bytes, audited status | Report deletion failure; never claim success | Discard hash/inventory and deletion-failure tests |
| Abandoned camera tracks | Frontend lifecycle | Idempotent stop on capture, stop, pagehide, navigation, error | Force inactive/failed state | Mock track stop count for every path |
| Visual prompt injection | Proposal/agent boundary | Treat text as quoted evidence; fixed goal; no tool authority | Draft only or reject | Malicious sign/QR cannot trigger tool mock |
| Decompression bomb | Decoder | Encoded, dimension, pixel, and decoder bomb limits | Reject and delete | Oversized compressed image fixture |
| Malformed image | Intake/decoder | MIME, magic, complete decode, re-encode | Reject and delete | Truncated/polyglot/corrupt fixtures |
| MIME spoofing | API/decoder | Compare declared type, magic, and decoded format | `image_type_invalid` | JPEG-as-PNG and PNG-as-JPEG tests |
| Owner-scope bypass | API/persistence | Trusted owner dependency and composite owner keys | Uniform unavailable response | Cross-owner read/write/delete tests |
| CSRF | Browser/API | Same-origin Origin, Fetch Metadata, session CSRF token | 403 without mutation | Cross-origin and missing-token tests |
| Arbitrary file write | Media store | Generated IDs, fixed roots, containment check, no client path | Reject without write | Traversal and separator corpus |
| Arbitrary file serving | Media API | Owner-scoped lookup and exact media ID; no generic path | Uniform 404 | Traversal/unknown/cross-owner tests |
| Local path disclosure | Errors/status/provenance | Generated locators and sanitized errors | Fixed error code only | Path marker absent from all surfaces |
| Model overclaim | Proposal contract | Epistemic labels, uncertainty, review state | Draft cannot become fact | Schema and rendered-label tests |
| External upload without consent | Processing adapter | No external adapter in v1; network disabled | Fail closed locally | Network-denial and no-request tests |
| Person identification | Proposal policy | Neutral non-identifying descriptions; prohibited fields | Refuse identifying output | Person-scene policy fixtures |
| Hidden third-party script | CSP/packaging | Exact same-origin asset, no generic static mount/CDN | Asset unavailable rather than fallback | CSP, asset allowlist, offline browser tests |
| Memory exhaustion | Browser/API/decoder | One stream/frame, size and pixel limits, bounded streaming | Stop/reject and clean partial state | Boundary and concurrent-session tests |
| Session replay | API/domain | Opaque ID, current-state precondition, CSRF, expiry | `session_expired`/invalid transition | Duplicate and out-of-order command tests |
| Stale temporary media | Retention service | 15-minute expiry plus startup/shutdown cleanup | Record cleanup failure | Clock-controlled expiry/restart tests |
| Agent tool escalation | Agent/application boundary | Data-only draft; separate explicit task approval | No tool invocation | Tool spies remain unused for image instructions |

## Deterministic Test Matrix

Automated tests use mocked media APIs and temporary roots. Physical camera testing is
deferred to U5.1H.

| Area | Required deterministic coverage |
| --- | --- |
| Initial state | No permission request or stream on page load |
| Permission | Explicit enable, denial, unsupported browser, missing/busy device |
| Preview | Active preview and visible/non-color-only indicator |
| Capture | Exactly one frame; tracks stop immediately |
| Stop/cleanup | Stop, navigation, pagehide, disconnect, and error release all tracks |
| Retake/discard | Retake requires gesture; discard clears buffers and object URL |
| Media limits | Exact boundary tests for type, 5 MiB, dimensions, pixels, corruption, spoofing |
| Session | Immutable valid transitions; duplicate/out-of-order/replayed commands rejected |
| Expiry | Controlled-clock 15-minute expiry and restart cleanup |
| Ownership | Same-owner success; cross-owner read/write/delete indistinguishable failure |
| CSRF | Missing/wrong token, Origin, and Fetch Metadata fail without mutation |
| Persistence | No persistence before Save; explicit save writes checksum/provenance |
| Deletion | Successful delete and honest `deletion_failed` behavior |
| Goals | Exactly one allowed creation goal; bounded context and output schema |
| Proposal | Always draft; uncertainty and epistemic labels rendered |
| Agents | No action/tool call without a separate explicit approval |
| Prompt injection | Image text cannot change policy, call tools, or open URLs |
| Network | No external request from page, server, or processing path |
| Headers | Page-specific camera permission, microphone denial, restrictive CSP |
| Packaging | Exact camera asset present in frozen graph/bundle in U5.1H |
| Installer | Installed local permission, cleanup, and retained user-data policy in U5.1H |
| Accessibility | Keyboard, focus, labels, announcements, reduced motion, mobile width |

## Implementation Slices

### U5.1B - Camera session/domain contracts

States, goals, errors, retention, provenance, and transition tests. No browser camera.

### U5.1C - Camera preview sandbox

Explicit permission, local preview, active indicator, stop, navigation cleanup, and
mocked media tests. No upload.

### U5.1D - Ephemeral still capture

One frame in browser memory, client bounds, preview, retake, discard, and buffer
cleanup. No persistence.

### U5.1E - Backend ephemeral media session

Owner-scoped session, raw bounded upload, checksum, safe decode, temporary storage,
expiry, and cleanup. No semantic model integration.

### U5.1F - Creation proposal workflow

Selected goal, separately approved local interpretation/structuring component,
bounded draft, epistemic labels, and no automatic save or action.

### U5.1G - Explicit save, delete, and provenance

Approved persistence, retention visibility, deletion audit, provenance, and replay.

### U5.1H - Frozen application and physical-camera verification

Package assets/dependencies, rebuild, browser permission on supported hardware,
privacy, cleanup, restart, installer refresh, and offline verification.

## Acceptance Criteria

- Architecture defines a still-only, user-triggered, local-first camera surface.
- Permission is never requested on load or by an agent.
- Active access is visible and always stoppable.
- Tracks stop after capture and on every cleanup/error path.
- Capture is browser-memory-only until explicit proposal/save action.
- Backend intake is bounded, type/decode/dimension validated, owner-scoped, and CSRF
  protected.
- Temporary media expires after 15 minutes and deletion status is honest.
- Save, delete, provenance, and epistemic contracts require explicit approval.
- Image content cannot grant authority or trigger tools.
- External frame disclosure is absent from v1.
- Threats have fail-closed mitigations and deterministic tests.
- No implementation slice begins without separate approval.

## Deferred Decisions

- Which local semantic vision component, if any, is acceptable for U5.1F.
- Whether U5.1E session metadata is database-backed or uses an equally reviewable
  restart-safe manifest before U5.1G.
- Exact camera table split and relationship to existing artifact records.
- Whether saved frames use original validated encoding or deterministic re-encoding.
- Exact page-specific `media-src` allowance required by supported browsers.
- Camera selector persistence; v1 should not persist it by default.
- Supported browser/version matrix and device-label wording.
- Whether a future explicit external-processing gate will ever be approved.
- Retention defaults for saved images and proposals beyond explicit user selection.

These decisions do not block U5.1B, which contains contracts only and no camera
access.
