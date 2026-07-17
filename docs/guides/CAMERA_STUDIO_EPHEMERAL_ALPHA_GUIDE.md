# Camera Studio Ephemeral Alpha Guide

Status: internal ephemeral alpha. This guide describes the local Camera Studio
workflow available at `/workbench/camera`.

## Before You Start

- Use a current browser in a secure local context that supports camera access.
- Keep the OrbitMind page open while you work. Reload the page if the page reports
  that camera submission authority is stale.
- This alpha is intentionally still-only and temporary. It does not permanently
  save media, analyze images, or execute a proposal.

## Explicit Workflow

1. Open `/workbench/camera`. The camera is inactive when the page loads.
2. Select **Enable camera**. Only this action requests browser camera permission.
3. Approve the browser permission if you want a local preview. The page shows a
   visible `CAMERA ACTIVE` state while a camera stream is running.
4. Select **Capture frame** to make one still image. Capture stops the camera
   tracks immediately.
5. Review the captured JPEG or PNG held in browser memory. Select **Retake** to
   clear it and explicitly request a new preview, or **Discard** to clear it and
   remain inactive.
6. Select **Create temporary session** to send that raw Blob to the same-origin
   local backend. This is the first action that creates temporary server state.
7. Select one creation goal, optionally enter bounded context, then select
   **Create proposal**. The resulting proposal is an inert temporary record only.
8. Select **Discard temporary server frame** to remove the temporary frame and any
   attached proposal together. Otherwise, temporary server state expires after
   15 minutes.

No action is retried automatically. The page does not poll, download media, retrieve
stored image bytes, or perform an action from a proposal.

## Controls

| Control | Effect |
| --- | --- |
| **Enable camera** | Explicitly requests one local video stream from the browser. |
| **Camera** selector | Switches to a selected browser-exposed video input after stopping the current stream. |
| **Stop camera** | Stops all active tracks and clears the local preview. |
| **Captured image format** | Selects JPEG or PNG for the next still capture. |
| **Capture frame** | Captures one local still, stops the stream, and holds the Blob only in browser memory. |
| **Retake** | Clears the local still and explicitly starts a new preview request. |
| **Discard** | Clears the local still and object URL without submitting it. |
| **Create temporary session** | Explicitly uploads the raw JPEG or PNG Blob to the local same-origin endpoint. |
| **Creation goal** | Chooses one bounded intent for one temporary proposal. |
| **Optional user context** | Adds up to 500 normalized code points of inert text. `Other` requires non-empty context. |
| **Create proposal** | Creates one proposal-only record from the selected goal, inert context, and stored frame facts. |
| **Discard temporary server frame** | Removes the server frame and its attached proposal. |

The available goals are:

- `visual_reference` - Use as a visual reference
- `documentation` - Prepare documentation
- `transformation_request` - Prepare a transformation request
- `explanation_request` - Prepare an explanation request
- `other` - Requires non-empty context

## Local Capture Behavior

The browser requests video only. Microphone access is disabled and no audio track is
requested. Capture is limited to one JPEG or PNG still with JPEG quality `0.90`, a
maximum of 1920 by 1080 pixels, and a maximum encoded size of 5,000,000 bytes. Larger
input dimensions are reduced without upscaling.

The preview, local Blob, and object URL are private browser-memory state. Retake,
local Discard, successful session creation, camera stop, a disconnected track,
pagehide, and BFCache restoration clear the relevant local state. The page does not
use browser storage for captured media or authority values.

## Temporary Server Session

Creating a temporary session sends the raw Blob to the exact local API route:

`POST /workbench/camera/api/sessions`

The backend accepts only bounded JPEG or PNG data, verifies the declared and detected
types agree, checks dimensions, rejects decompression-bomb conditions, creates a fresh
normalized raster, and stores only that temporary normalized frame. It generates the
filename and checksum internally. There is no media-download or image-content
retrieval endpoint. The available `GET` session route returns metadata only; it does
not return image bytes.

At most eight active sessions and 40,000,000 normalized bytes are retained. Each
session has an absolute 900-second lifetime. Startup, lazy expiry, explicit discard,
and application shutdown all perform bounded cleanup. File removal is best effort, so
the alpha does not promise deletion when the operating system prevents it.

## Proposal Behavior

The proposal route is:

`POST /workbench/camera/api/sessions/{session_id}/proposal`

One active temporary session can have one proposal. The proposal is `proposal_only`,
has execution status `not_authorized`, analysis status `not_performed`, and requires
human approval for any future work. It inherits its parent session's expiry and is
removed with that parent. Proposal creation reads stored frame facts but does not open
or decode the image file, invoke Pillow, construct a prompt, invoke a model or agent,
or perform an external request.

## Authority And Privacy

The camera page uses an HttpOnly, SameSite=Strict page-session cookie and a private
CSRF token. Mutating requests require exact loopback Host and Origin values,
`Sec-Fetch-Site: same-origin`, the current CSRF token, and the appropriate exact
route scope. Tokens rotate atomically after accepted request authority. A stale page,
lost response, back-forward-cache restoration, or application restart fails closed;
reload the camera page rather than attempting to recover authority.

Media-session capability and CSRF authority are separate. A capability does not
substitute for CSRF, and CSRF does not substitute for a session capability. The page
does not expose capability values in URLs or render them into the DOM.

This alpha does not retain an original filename, device label after local preview use,
raw upload bytes as final storage, internal media paths, plaintext server-side CSRF
tokens, or media in browser storage. It performs no facial recognition, biometric
processing, OCR, person identification, object classification, scene interpretation,
surveillance, telemetry, or external AI call.

## Troubleshooting

- **Permission denied:** Select **Enable camera** again only after changing the
  browser permission. The camera remains inactive until an explicit retry.
- **Camera not found:** Connect or enable a compatible camera in the operating system,
  then select **Enable camera** again.
- **Camera in use:** Close the competing application or release its camera use, then
  explicitly enable the camera again.
- **Camera disconnected:** The page stops the stream and clears local capture state.
  Reconnect the device and explicitly enable the camera again.
- **Authority stale or reload required:** Reload `/workbench/camera`. Do not retry an
  ambiguous submission or proposal request automatically.
- **Temporary session result unknown:** Reload before beginning another workflow. Any
  accepted temporary state remains bounded by the 15-minute expiry.

## Leaving the Page

Select **Stop camera** before leaving when a preview is active. Pagehide and BFCache
handling also stop tracks and clear local camera authority. Leaving the page does not
create a new cleanup request, and it does not make an inert proposal execute.

## Known Limits

This is not production-ready, a public alpha, a monitoring feature, an authenticated
account system, or a security certification. Automated validation used mocked browser
media APIs only; it did not verify physical camera hardware. There is no permanent
media storage, durable proposal storage, AI understanding, image transformation,
sharing, publishing, or background recording in this alpha.
