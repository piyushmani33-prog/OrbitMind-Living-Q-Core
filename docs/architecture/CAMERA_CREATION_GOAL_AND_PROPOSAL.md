# Camera Creation Goal And Proposal

## Purpose

U5.1G adds one explicit, ephemeral statement of user intent to an already accepted
temporary camera-media session. A proposal is inert data. It records neither an image
interpretation nor an instruction to perform work, and it cannot save, publish,
execute, retrieve, or transform media.

## Closed Goals

| Machine value | User-facing label | Meaning |
| --- | --- | --- |
| `visual_reference` | Use as a visual reference | The user may later use the frame as a reference. |
| `documentation` | Prepare documentation | The user may later request documentation. |
| `transformation_request` | Prepare a transformation request | The user may later request a transformation. |
| `explanation_request` | Prepare an explanation request | The user may later request an explanation. |
| `other` | Other | Records only the supplied context. |

The taxonomy does not include identification, tracking, diagnosis, authorization,
publishing, execution, monitoring, device control, surveillance, or biometrics.

## Contract And Authority

`CameraCreationProposal` is a framework-free immutable record. Its exact public
fields are the contract version, proposal and session identifiers, goal, user context,
state, execution and analysis statuses, timestamps, authoritative media facts,
retention status, and the human-approval requirement. It deliberately excludes media
paths, filenames, bytes, URLs, capabilities, CSRF material, device identifiers, model
outputs, and agent state.

The proposal endpoint is the sole new route:

`POST /workbench/camera/api/sessions/{session_id}/proposal`

It requires the current camera page cookie, the existing exact loopback Host and
Origin checks, `Sec-Fetch-Site: same-origin`, current CSRF token, and the existing
media-session capability. The CSRF token rotates before media capability, session, or
body validation failures. The parent session DELETE route remains the only deletion
route.

The JSON body is exactly `goal` and `user_context`, is limited to 4096 bytes, rejects
duplicate or extra fields, and accepts no nested data, image payload, filename, model,
agent, prompt, or tool selection. `user_context` is `null` or text normalized to NFC;
CRLF and CR are canonicalized to LF, outer whitespace is trimmed, LF is the only
permitted control character, and the normalized value is limited to 500 Unicode code
points. `other` requires non-empty normalized context. Context is inert untrusted text,
never parsed as HTML, Markdown, or a template, and is not logged.

## Lifecycle And Privacy

There is at most one proposal on an active in-memory media-session record. The proposal
uses only the record's authoritative metadata and is created without opening, reading,
decoding, hashing, or otherwise accessing the media file. It has a fresh independent
32-byte `secrets.token_urlsafe(32)` base64url identifier and does not extend the parent
expiry or affect media capacity.

Discard, expiry, lazy cleanup, startup cleanup, and application shutdown remove the
parent record and therefore the attached proposal. No proposal file, registry,
database record, migration, or persistent artifact exists. Deletion failure leaves the
parent record intact, so its proposal cannot outlive it.

The browser displays only validated data with text-only DOM writes. It never puts
context into `innerHTML`; clears proposal, goal, context, session, and authority on
pagehide or BFCache restoration; and never retries an ambiguous proposal result.

## Human Approval And Future Boundaries

Every proposal is `proposal_only`, `not_authorized`, `not_performed`, ephemeral, and
requires human approval. Only Piyush Mani's explicit future approval can authorize
execution or persistence. A future model boundary must separately review model
selection, image handling, prompt-injection defenses, provenance, consent, and any
connected processing. Text visible in an image remains untrusted visual content and
can never grant authority or execute instructions.

## Test Matrix

Focused tests cover strict goal/context contracts, ID independence, CSRF rotation,
capability and session authority, request bounds, one-proposal atomicity, no-image
access, lifecycle cascade, static browser controls and response validation, and a
mocked-browser harness. Existing media, CSRF, lifecycle, Workbench security, camera
preview, persistence restart, and architecture-boundary coverage remains a regression
requirement.

## Non-Goals

U5.1G performs no image analysis, OCR, face processing, model or agent invocation,
prompt construction, proposal execution, media retrieval/download, persistence,
migration, artifact generation, external network activity, or physical-camera test.
