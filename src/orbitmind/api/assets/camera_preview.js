(function () {
  "use strict";

  const enableButton = document.getElementById("camera-enable");
  const stopButton = document.getElementById("camera-stop");
  const captureButton = document.getElementById("camera-capture");
  const captureFormat = document.getElementById("camera-capture-format");
  const retakeButton = document.getElementById("camera-retake");
  const discardButton = document.getElementById("camera-discard");
  const createSessionButton = document.getElementById("camera-create-session");
  const serverDiscardButton = document.getElementById("camera-server-discard");
  const deviceField = document.getElementById("camera-device-field");
  const deviceSelect = document.getElementById("camera-device");
  const activeIndicator = document.getElementById("camera-active-indicator");
  const activeLabel = document.getElementById("camera-active-label");
  const supportStatus = document.getElementById("camera-support-status");
  const statusRegion = document.getElementById("camera-status");
  const video = document.getElementById("camera-preview");
  const capturedPanel = document.getElementById("camera-captured-panel");
  const capturedImage = document.getElementById("camera-captured-image");
  const captureMetadata = document.getElementById("camera-capture-metadata");
  const captureMediaType = document.getElementById("camera-capture-media-type");
  const captureWidth = document.getElementById("camera-capture-width");
  const captureHeight = document.getElementById("camera-capture-height");
  const captureSize = document.getElementById("camera-capture-size");
  const serverSessionPanel = document.getElementById("camera-server-session-panel");
  const serverMediaType = document.getElementById("camera-server-media-type");
  const serverWidth = document.getElementById("camera-server-width");
  const serverHeight = document.getElementById("camera-server-height");
  const serverSize = document.getElementById("camera-server-size");
  const serverExpires = document.getElementById("camera-server-expires");
  const serverRetention = document.getElementById("camera-server-retention");
  const proposalControls = document.getElementById("camera-proposal-controls");
  const proposalGoal = document.getElementById("camera-proposal-goal");
  const proposalContext = document.getElementById("camera-proposal-context");
  const createProposalButton = document.getElementById("camera-create-proposal");
  const proposalPanel = document.getElementById("camera-proposal-panel");
  const proposalGoalValue = document.getElementById("camera-proposal-goal-value");
  const proposalContextValue = document.getElementById("camera-proposal-context-value");
  const proposalState = document.getElementById("camera-proposal-state");
  const proposalExecution = document.getElementById("camera-proposal-execution");
  const proposalAnalysis = document.getElementById("camera-proposal-analysis");
  const proposalExpires = document.getElementById("camera-proposal-expires");
  const proposalApproval = document.getElementById("camera-proposal-approval");

  if (
    !enableButton ||
    !stopButton ||
    !captureButton ||
    !captureFormat ||
    !retakeButton ||
    !discardButton ||
    !createSessionButton ||
    !serverDiscardButton ||
    !deviceField ||
    !deviceSelect ||
    !activeIndicator ||
    !activeLabel ||
    !supportStatus ||
    !statusRegion ||
    !video ||
    !capturedPanel ||
    !capturedImage ||
    !captureMetadata ||
    !captureMediaType ||
    !captureWidth ||
    !captureHeight ||
    !captureSize ||
    !serverSessionPanel ||
    !serverMediaType ||
    !serverWidth ||
    !serverHeight ||
    !serverSize ||
    !serverExpires ||
    !serverRetention ||
    !proposalControls ||
    !proposalGoal ||
    !proposalContext ||
    !createProposalButton ||
    !proposalPanel ||
    !proposalGoalValue ||
    !proposalContextValue ||
    !proposalState ||
    !proposalExecution ||
    !proposalAnalysis ||
    !proposalExpires ||
    !proposalApproval
  ) {
    return;
  }

  const MAX_CAPTURE_WIDTH = 1920;
  const MAX_CAPTURE_HEIGHT = 1080;
  const MAX_CAPTURE_BYTES = 5000000;
  const JPEG_QUALITY = 0.90;
  const CAPTURE_TYPES = Object.freeze(["image/jpeg", "image/png"]);
  const OPAQUE_TOKEN_PATTERN = /^[A-Za-z0-9_-]{43}$/;
  const CHECKSUM_PATTERN = /^[a-f0-9]{64}$/;
  const CSRF_META_NAME = "orbitmind-camera-csrf";
  const CSRF_REQUEST_HEADER = "X-OrbitMind-Camera-CSRF";
  const CSRF_NEXT_HEADER = "X-OrbitMind-Camera-CSRF-Next";
  const CAPABILITY_HEADER = "X-OrbitMind-Camera-Capability";
  const SESSION_ENDPOINT = "/workbench/camera/api/sessions";
  const PROPOSAL_ENDPOINT_SUFFIX = "/proposal";
  const MAX_PROPOSAL_CONTEXT_CODEPOINTS = 500;
  const PROPOSAL_GOALS = Object.freeze([
    "visual_reference",
    "documentation",
    "transformation_request",
    "explanation_request",
    "other",
  ]);
  const PROPOSAL_GOAL_LABELS = Object.freeze({
    visual_reference: "Use as a visual reference",
    documentation: "Prepare documentation",
    transformation_request: "Prepare a transformation request",
    explanation_request: "Prepare an explanation request",
    other: "Other",
  });
  const ALLOWED_ERROR_CODES = Object.freeze([
    "camera_ephemeral_capacity_exceeded",
    "camera_proposal_already_exists",
    "camera_proposal_context_invalid",
    "camera_proposal_goal_invalid",
    "camera_proposal_request_invalid",
    "camera_request_csrf_invalid",
    "camera_session_not_found",
    "deletion_failed",
    "image_decode_failed",
    "image_dimensions_invalid",
    "image_too_large",
    "image_type_invalid",
    "temporary_storage_failed",
  ]);
  const messages = Object.freeze({
    camera_not_supported: "Camera preview is not supported in this secure browser context.",
    camera_permission_denied: "Camera permission was denied. Select Enable camera to try again.",
    camera_not_found: "No camera is available.",
    camera_in_use: "The camera is unavailable or already in use.",
    camera_disconnected: "The active camera disconnected.",
    camera_start_failed: "Camera preview could not start safely.",
    camera_request_csrf_invalid: "Camera submission authority is no longer valid. Reload the page.",
    camera_ephemeral_capacity_exceeded: "Temporary camera capacity is unavailable. Try again later.",
    camera_proposal_context_invalid: "The proposal context is invalid.",
    camera_proposal_goal_invalid: "Choose one approved creation goal.",
    camera_proposal_request_invalid: "The proposal request is invalid.",
    camera_session_not_found: "The temporary server frame is no longer controllable.",
    capture_failed: "The frame could not be captured safely.",
    deletion_failed: "The temporary server frame could not be discarded. Select discard to try again.",
    image_decode_failed: "The captured image could not be accepted.",
    image_dimensions_invalid: "The camera frame dimensions are unavailable or invalid.",
    image_type_invalid: "The captured image format is invalid.",
    image_too_large: "The captured image exceeds the 5,000,000-byte limit.",
    temporary_session_failed: "The temporary session could not be created safely.",
    temporary_storage_failed: "Temporary camera storage is unavailable.",
  });

  let state = "idle";
  let activeStream = null;
  let selectedDeviceId = "";
  let capturedBlob = null;
  let capturedObjectUrl = "";
  let csrfToken = "";
  let privateSessionId = "";
  let privateSessionCapability = "";
  let authoritativeMetadata = null;
  let privateProposal = null;
  let modifyingRequestInFlight = false;
  let captureGeneration = 0;
  let destroyed = false;
  const endedHandlers = new Map();

  function mediaApiAvailable() {
    return Boolean(
      window.isSecureContext &&
        navigator.mediaDevices &&
        typeof navigator.mediaDevices.getUserMedia === "function"
    );
  }

  function hasValidOpaqueToken(value) {
    return typeof value === "string" && OPAQUE_TOKEN_PATTERN.test(value);
  }

  function hasCurrentCsrfAuthority() {
    return hasValidOpaqueToken(csrfToken);
  }

  function hasPrivateServerSession() {
    return hasValidOpaqueToken(privateSessionId) && hasValidOpaqueToken(privateSessionCapability);
  }

  function updateControls() {
    const previewVisible = state === "active" || state === "capturing";
    const localFrameVisible = state === "captured" && Boolean(capturedBlob);
    const serverFrameVisible = hasPrivateServerSession();
    const localWorkflowBusy = ["requesting", "active", "capturing", "submitting"].includes(state);
    const serverWorkflowBusy = [
      "submitting",
      "submitted_ephemeral",
      "selecting_goal",
      "proposing",
      "proposal_created",
      "proposal_failed",
      "discarding_server",
    ].includes(state);
    const mayModify = hasCurrentCsrfAuthority() && !modifyingRequestInFlight && !destroyed;

    enableButton.disabled = destroyed || localWorkflowBusy || serverWorkflowBusy;
    stopButton.disabled = state !== "active";
    captureButton.disabled = state !== "active";
    captureFormat.disabled = state === "capturing" || state === "captured" || serverWorkflowBusy;
    deviceSelect.disabled = state !== "active" || deviceSelect.children.length <= 1;
    activeIndicator.hidden = !previewVisible;
    capturedPanel.hidden = !localFrameVisible;
    retakeButton.hidden = !localFrameVisible;
    discardButton.hidden = !localFrameVisible;
    createSessionButton.disabled = !(
      state === "captured" &&
      Boolean(capturedBlob) &&
      mayModify &&
      !hasPrivateServerSession()
    );
    serverSessionPanel.hidden = !serverFrameVisible;
    proposalControls.hidden = !serverFrameVisible || Boolean(privateProposal);
    proposalPanel.hidden = !privateProposal;
    const maySelectProposal = ["submitted_ephemeral", "selecting_goal", "proposal_failed"].includes(state);
    proposalGoal.disabled = !serverFrameVisible || !maySelectProposal || !mayModify;
    proposalContext.disabled = !serverFrameVisible || !maySelectProposal || !mayModify;
    createProposalButton.disabled = !(
      state === "selecting_goal" &&
      hasValidProposalSelection() &&
      mayModify &&
      serverFrameVisible &&
      !privateProposal
    );
    serverDiscardButton.hidden = !serverFrameVisible;
    serverDiscardButton.disabled = !(
      ["submitted_ephemeral", "selecting_goal", "proposal_created", "proposal_failed"].includes(state) &&
      serverFrameVisible &&
      mayModify
    );
  }

  function setState(nextState, message, isError) {
    state = nextState;
    updateControls();
    statusRegion.textContent = message;
    statusRegion.classList.toggle("error", Boolean(isError));
  }

  function sanitizeLabel(value, fallback) {
    if (typeof value !== "string") {
      return fallback;
    }
    const clean = value.replace(/[\u0000-\u001f\u007f-\u009f]/g, "").trim().slice(0, 128);
    if (!clean || clean.includes("://") || clean.includes("/") || clean.includes("\\")) {
      return fallback;
    }
    return clean;
  }

  function errorCode(error) {
    const name = error && typeof error.name === "string" ? error.name : "";
    if (name === "NotAllowedError") {
      return "camera_permission_denied";
    }
    if (name === "NotFoundError" || name === "DevicesNotFoundError") {
      return "camera_not_found";
    }
    if (name === "NotReadableError" || name === "TrackStartError") {
      return "camera_in_use";
    }
    return "camera_start_failed";
  }

  function captureError(code) {
    return { captureCode: code };
  }

  function captureErrorCode(error) {
    const code = error && typeof error.captureCode === "string" ? error.captureCode : "";
    return ["image_dimensions_invalid", "capture_failed", "image_type_invalid", "image_too_large"].includes(
      code
    )
      ? code
      : "capture_failed";
  }

  function removeEndedHandlers(stream) {
    if (!stream) {
      return;
    }
    stream.getVideoTracks().forEach(function (track) {
      const handler = endedHandlers.get(track);
      if (handler) {
        track.removeEventListener("ended", handler);
        endedHandlers.delete(track);
      }
    });
  }

  function stopStream(stream) {
    if (!stream) {
      return;
    }
    removeEndedHandlers(stream);
    stream.getTracks().forEach(function (track) {
      track.stop();
    });
  }

  function clearDeviceChoices() {
    selectedDeviceId = "";
    deviceSelect.replaceChildren();
    deviceSelect.disabled = true;
    deviceField.hidden = true;
  }

  function clearPreview(clearDevices) {
    const stream = activeStream;
    activeStream = null;
    stopStream(stream);
    video.pause();
    video.srcObject = null;
    activeLabel.textContent = "";
    activeLabel.hidden = true;
    activeIndicator.hidden = true;
    if (clearDevices) {
      clearDeviceChoices();
    }
  }

  function safeRevokeObjectUrl(objectUrl) {
    if (!objectUrl) {
      return;
    }
    try {
      URL.revokeObjectURL(objectUrl);
    } catch (_error) {
      // Best-effort memory cleanup must not expose browser-specific details.
    }
  }

  function clearCapturedFrame() {
    safeRevokeObjectUrl(capturedObjectUrl);
    capturedObjectUrl = "";
    capturedBlob = null;
    capturedImage.removeAttribute("src");
    capturedImage.hidden = true;
    captureMetadata.hidden = true;
    captureMediaType.textContent = "";
    captureWidth.textContent = "";
    captureHeight.textContent = "";
    captureSize.textContent = "";
    capturedPanel.hidden = true;
    retakeButton.hidden = true;
    discardButton.hidden = true;
    createSessionButton.disabled = true;
  }

  function clearServerSession() {
    privateSessionId = "";
    privateSessionCapability = "";
    authoritativeMetadata = null;
    serverMediaType.textContent = "";
    serverWidth.textContent = "";
    serverHeight.textContent = "";
    serverSize.textContent = "";
    serverExpires.textContent = "";
    serverRetention.textContent = "";
    clearProposal();
    serverDiscardButton.hidden = true;
    serverSessionPanel.hidden = true;
  }

  function clearProposal() {
    privateProposal = null;
    proposalGoal.value = "";
    proposalContext.value = "";
    proposalGoalValue.textContent = "";
    proposalContextValue.textContent = "";
    proposalState.textContent = "";
    proposalExecution.textContent = "";
    proposalAnalysis.textContent = "";
    proposalExpires.textContent = "";
    proposalApproval.textContent = "";
    proposalControls.hidden = true;
    proposalPanel.hidden = true;
    createProposalButton.disabled = true;
  }

  function clearCsrfAuthority() {
    csrfToken = "";
  }

  function releaseCanvas(canvas, context) {
    if (!canvas) {
      return;
    }
    try {
      if (context) {
        context.clearRect(0, 0, canvas.width, canvas.height);
      }
      canvas.width = 0;
      canvas.height = 0;
    } catch (_error) {
      // The canvas is function-local and is discarded even if explicit clearing fails.
    }
  }

  function fail(code) {
    captureGeneration += 1;
    clearPreview(true);
    clearCapturedFrame();
    setState("failed", code + ": " + messages[code], true);
  }

  function enterAuthorityStale(message, clearLocalFrame) {
    modifyingRequestInFlight = false;
    clearCsrfAuthority();
    clearServerSession();
    if (clearLocalFrame) {
      clearCapturedFrame();
    }
    clearPreview(true);
    setState("authority_stale", message, true);
  }

  function stopCamera(message) {
    if (state !== "active") {
      return;
    }
    state = "stopping";
    clearPreview(true);
    setState("idle", message || "Camera stopped.", false);
  }

  function onTrackEnded(stream, track) {
    if (activeStream !== stream || !stream.getTracks().includes(track)) {
      return;
    }
    fail("camera_disconnected");
  }

  function registerEndedHandlers(stream) {
    stream.getVideoTracks().forEach(function (track) {
      const handler = function () {
        onTrackEnded(stream, track);
      };
      endedHandlers.set(track, handler);
      track.addEventListener("ended", handler, { once: true });
    });
  }

  function setActiveLabel(stream) {
    const tracks = stream.getVideoTracks();
    const label = tracks.length > 0 ? sanitizeLabel(tracks[0].label, "Camera") : "Camera";
    activeLabel.textContent = label;
    activeLabel.hidden = false;
  }

  async function populateDeviceChoices() {
    if (!navigator.mediaDevices || typeof navigator.mediaDevices.enumerateDevices !== "function") {
      clearDeviceChoices();
      return;
    }
    let devices;
    try {
      devices = await navigator.mediaDevices.enumerateDevices();
    } catch (_error) {
      clearDeviceChoices();
      return;
    }
    if (state !== "active") {
      return;
    }
    const cameras = devices.filter(function (device) {
      return device.kind === "videoinput";
    });
    deviceSelect.replaceChildren();
    cameras.forEach(function (device, index) {
      const option = document.createElement("option");
      option.value = device.deviceId;
      option.textContent = sanitizeLabel(device.label, "Camera " + String(index + 1));
      deviceSelect.appendChild(option);
    });
    if (
      selectedDeviceId &&
      cameras.some(function (device) {
        return device.deviceId === selectedDeviceId;
      })
    ) {
      deviceSelect.value = selectedDeviceId;
    }
    deviceField.hidden = cameras.length <= 1;
    updateControls();
  }

  async function startCamera(deviceId) {
    if (
      destroyed ||
      [
        "requesting",
        "active",
        "capturing",
        "captured",
        "submitting",
        "submitted_ephemeral",
        "discarding_server",
        "stopping",
      ].includes(state)
    ) {
      return;
    }
    if (!mediaApiAvailable()) {
      fail("camera_not_supported");
      return;
    }
    setState("requesting", "Requesting camera permission...", false);
    const constraints = {
      audio: false,
      video: deviceId ? { deviceId: { exact: deviceId } } : true,
    };
    let stream = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia(constraints);
      if (destroyed) {
        stopStream(stream);
        return;
      }
      activeStream = stream;
      selectedDeviceId = deviceId || "";
      registerEndedHandlers(stream);
      video.srcObject = stream;
      await video.play();
      setActiveLabel(stream);
      setState("active", "Camera preview is active and remains local to this browser.", false);
      await populateDeviceChoices();
    } catch (error) {
      if (stream && activeStream !== stream) {
        stopStream(stream);
      }
      fail(errorCode(error));
    }
  }

  function validatedCaptureDimensions() {
    const sourceWidth = video.videoWidth;
    const sourceHeight = video.videoHeight;
    if (
      !Number.isFinite(sourceWidth) ||
      !Number.isFinite(sourceHeight) ||
      !Number.isInteger(sourceWidth) ||
      !Number.isInteger(sourceHeight) ||
      sourceWidth <= 0 ||
      sourceHeight <= 0
    ) {
      throw captureError("image_dimensions_invalid");
    }
    const scale = Math.min(1, MAX_CAPTURE_WIDTH / sourceWidth, MAX_CAPTURE_HEIGHT / sourceHeight);
    const width = Math.max(1, Math.floor(sourceWidth * scale));
    const height = Math.max(1, Math.floor(sourceHeight * scale));
    return { width, height };
  }

  function encodeCanvas(canvas, mediaType) {
    return new Promise(function (resolve) {
      canvas.toBlob(
        resolve,
        mediaType,
        mediaType === "image/jpeg" ? JPEG_QUALITY : undefined
      );
    });
  }

  function showCapturedFrame(blob, objectUrl, dimensions) {
    capturedBlob = blob;
    capturedObjectUrl = objectUrl;
    capturedImage.src = capturedObjectUrl;
    capturedImage.hidden = false;
    captureMediaType.textContent = blob.type;
    captureWidth.textContent = String(dimensions.width);
    captureHeight.textContent = String(dimensions.height);
    captureSize.textContent = String(blob.size);
    captureMetadata.hidden = false;
    capturedPanel.hidden = false;
  }

  async function captureFrame() {
    if (state !== "active" || !activeStream || video.srcObject !== activeStream) {
      return;
    }
    const mediaType = captureFormat.value;
    if (!CAPTURE_TYPES.includes(mediaType)) {
      fail("image_type_invalid");
      return;
    }

    const generation = ++captureGeneration;
    setState("capturing", "Capturing one local frame...", false);
    let canvas = null;
    let context = null;
    let newObjectUrl = "";
    try {
      const dimensions = validatedCaptureDimensions();
      canvas = document.createElement("canvas");
      canvas.width = dimensions.width;
      canvas.height = dimensions.height;
      context = canvas.getContext("2d");
      if (!context) {
        throw captureError("capture_failed");
      }
      context.drawImage(video, 0, 0, dimensions.width, dimensions.height);
      const blob = await encodeCanvas(canvas, mediaType);
      if (destroyed || generation !== captureGeneration || state !== "capturing") {
        return;
      }
      if (!blob || !Number.isInteger(blob.size) || blob.size < 1) {
        throw captureError("capture_failed");
      }
      if (!CAPTURE_TYPES.includes(blob.type) || blob.type !== mediaType) {
        throw captureError("image_type_invalid");
      }
      if (!Number.isFinite(blob.size) || blob.size > MAX_CAPTURE_BYTES) {
        throw captureError("image_too_large");
      }
      newObjectUrl = URL.createObjectURL(blob);
      if (!newObjectUrl || destroyed || generation !== captureGeneration) {
        throw captureError("capture_failed");
      }
      showCapturedFrame(blob, newObjectUrl, dimensions);
      newObjectUrl = "";
      clearPreview(false);
      setState(
        "captured",
        "Frame captured in browser memory. The camera has been stopped.",
        false
      );
    } catch (error) {
      safeRevokeObjectUrl(newObjectUrl);
      if (!destroyed && generation === captureGeneration) {
        fail(captureErrorCode(error));
      }
    } finally {
      releaseCanvas(canvas, context);
    }
  }

  function removeMetaToken(meta) {
    meta.setAttribute("content", "");
    if (typeof meta.remove === "function") {
      meta.remove();
    } else if (meta.parentNode) {
      meta.parentNode.removeChild(meta);
    }
  }

  function captureInitialCsrfAuthority() {
    const metas = document.querySelectorAll('meta[name="' + CSRF_META_NAME + '"]');
    if (metas.length !== 1 || !hasValidOpaqueToken(metas[0].getAttribute("content") || "")) {
      clearCsrfAuthority();
      return false;
    }
    const token = metas[0].getAttribute("content") || "";
    csrfToken = "";
    csrfToken = token;
    removeMetaToken(metas[0]);
    return true;
  }

  function rotateCsrfAuthority(response) {
    const nextToken = response.headers.get(CSRF_NEXT_HEADER);
    if (!hasValidOpaqueToken(nextToken || "")) {
      clearCsrfAuthority();
      return false;
    }
    csrfToken = "";
    csrfToken = nextToken;
    return true;
  }

  function isApprovedJsonResponse(response) {
    const contentType = response.headers.get("Content-Type") || "";
    return contentType.toLowerCase().startsWith("application/json");
  }

  function isUtcTimestamp(value) {
    return typeof value === "string" && value.endsWith("Z") && Number.isFinite(Date.parse(value));
  }

  function isApprovedSessionResponse(body) {
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      return false;
    }
    const fields = Object.keys(body).sort();
    const expectedFields = [
      "content_checksum",
      "contract_version",
      "created_at",
      "encoded_size",
      "expires_at",
      "height",
      "media_type",
      "retention_status",
      "session_capability",
      "session_id",
      "state",
      "width",
    ];
    if (fields.length !== expectedFields.length || fields.some(function (field, index) {
      return field !== expectedFields[index];
    })) {
      return false;
    }
    if (
      body.contract_version !== 1 ||
      !hasValidOpaqueToken(body.session_id) ||
      !hasValidOpaqueToken(body.session_capability) ||
      body.session_id === body.session_capability ||
      body.state !== "frame_captured_ephemeral" ||
      body.retention_status !== "ephemeral" ||
      !CAPTURE_TYPES.includes(body.media_type) ||
      !Number.isInteger(body.width) ||
      !Number.isInteger(body.height) ||
      body.width < 1 ||
      body.width > MAX_CAPTURE_WIDTH ||
      body.height < 1 ||
      body.height > MAX_CAPTURE_HEIGHT ||
      !Number.isInteger(body.encoded_size) ||
      body.encoded_size < 1 ||
      body.encoded_size > MAX_CAPTURE_BYTES ||
      typeof body.content_checksum !== "string" ||
      !CHECKSUM_PATTERN.test(body.content_checksum) ||
      !isUtcTimestamp(body.created_at) ||
      !isUtcTimestamp(body.expires_at) ||
      Date.parse(body.expires_at) <= Date.parse(body.created_at)
    ) {
      return false;
    }
    return true;
  }

  function normalizedProposalContext(value) {
    if (typeof value !== "string") {
      return null;
    }
    const normalized = value.replace(/\r\n?/g, "\n").normalize("NFC").trim();
    if (
      /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]/.test(normalized) ||
      Array.from(normalized).length > MAX_PROPOSAL_CONTEXT_CODEPOINTS
    ) {
      return null;
    }
    return normalized;
  }

  function hasValidProposalSelection() {
    if (!PROPOSAL_GOALS.includes(proposalGoal.value)) {
      return false;
    }
    const context = normalizedProposalContext(proposalContext.value);
    return context !== null && (proposalGoal.value !== "other" || Boolean(context));
  }

  function isApprovedProposalResponse(body, goal, userContext) {
    if (!body || typeof body !== "object" || Array.isArray(body) || !authoritativeMetadata) {
      return false;
    }
    const fields = Object.keys(body).sort();
    const expectedFields = [
      "analysis_status",
      "content_checksum",
      "contract_version",
      "created_at",
      "encoded_size",
      "execution_status",
      "expires_at",
      "goal",
      "height",
      "human_approval_required",
      "media_type",
      "proposal_id",
      "retention_status",
      "session_id",
      "state",
      "user_context",
      "width",
    ];
    if (fields.length !== expectedFields.length || fields.some(function (field, index) {
      return field !== expectedFields[index];
    })) {
      return false;
    }
    return (
      body.contract_version === 1 &&
      hasValidOpaqueToken(body.proposal_id) &&
      body.session_id === privateSessionId &&
      body.goal === goal &&
      PROPOSAL_GOALS.includes(body.goal) &&
      body.user_context === userContext &&
      body.state === "proposal_only" &&
      body.execution_status === "not_authorized" &&
      body.analysis_status === "not_performed" &&
      body.human_approval_required === true &&
      body.retention_status === "ephemeral" &&
      body.expires_at === authoritativeMetadata.expires_at &&
      body.media_type === authoritativeMetadata.media_type &&
      body.width === authoritativeMetadata.width &&
      body.height === authoritativeMetadata.height &&
      body.encoded_size === authoritativeMetadata.encoded_size &&
      body.content_checksum === authoritativeMetadata.content_checksum &&
      isUtcTimestamp(body.created_at) &&
      isUtcTimestamp(body.expires_at) &&
      Date.parse(body.created_at) <= Date.parse(body.expires_at)
    );
  }

  async function boundedErrorCode(response) {
    if (!isApprovedJsonResponse(response)) {
      return "temporary_session_failed";
    }
    try {
      const body = await response.json();
      const code = body && body.detail && body.detail.code;
      return typeof code === "string" && ALLOWED_ERROR_CODES.includes(code)
        ? code
        : "temporary_session_failed";
    } catch (_error) {
      return "temporary_session_failed";
    }
  }

  function renderServerMetadata(metadata) {
    serverMediaType.textContent = metadata.media_type;
    serverWidth.textContent = String(metadata.width);
    serverHeight.textContent = String(metadata.height);
    serverSize.textContent = String(metadata.encoded_size);
    serverExpires.textContent = metadata.expires_at;
    serverRetention.textContent = metadata.retention_status;
  }

  function renderProposal(proposal) {
    proposalGoalValue.textContent = PROPOSAL_GOAL_LABELS[proposal.goal];
    proposalContextValue.textContent = proposal.user_context || "";
    proposalState.textContent = "Temporary proposal only";
    proposalExecution.textContent = "Not authorized";
    proposalAnalysis.textContent = "Not performed";
    proposalExpires.textContent = proposal.expires_at;
    proposalApproval.textContent = "Required";
  }

  function postFailureWithCurrentAuthority(code) {
    setState("captured", code + ": " + messages[code], true);
  }

  async function createTemporarySession() {
    if (
      state !== "captured" ||
      !capturedBlob ||
      !CAPTURE_TYPES.includes(capturedBlob.type) ||
      !Number.isInteger(capturedBlob.size) ||
      capturedBlob.size < 1 ||
      capturedBlob.size > MAX_CAPTURE_BYTES ||
      !hasCurrentCsrfAuthority() ||
      hasPrivateServerSession() ||
      modifyingRequestInFlight ||
      destroyed
    ) {
      return;
    }

    modifyingRequestInFlight = true;
    setState("submitting", "Creating a temporary server session...", false);
    try {
      const response = await fetch(SESSION_ENDPOINT, {
        method: "POST",
        body: capturedBlob,
        headers: {
          "Content-Type": capturedBlob.type,
          [CSRF_REQUEST_HEADER]: csrfToken,
        },
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
      });
      if (!rotateCsrfAuthority(response)) {
        enterAuthorityStale(
          "Submission authority is stale. Reload the page before camera submission can continue.",
          true
        );
        return;
      }
      if (response.status !== 201 || !isApprovedJsonResponse(response)) {
        if (response.status === 201) {
          enterAuthorityStale(
            "Submission result is unknown. Reload the page. Any accepted temporary frame will expire automatically.",
            true
          );
          return;
        }
        postFailureWithCurrentAuthority(await boundedErrorCode(response));
        return;
      }
      let body;
      try {
        body = await response.json();
      } catch (_error) {
        enterAuthorityStale(
          "Submission result is unknown. Reload the page. Any accepted temporary frame will expire automatically.",
          true
        );
        return;
      }
      if (!isApprovedSessionResponse(body)) {
        enterAuthorityStale(
          "Submission result is unknown. Reload the page. Any accepted temporary frame will expire automatically.",
          true
        );
        return;
      }
      privateSessionId = body.session_id;
      privateSessionCapability = body.session_capability;
      authoritativeMetadata = {
        content_checksum: body.content_checksum,
        contract_version: body.contract_version,
        created_at: body.created_at,
        encoded_size: body.encoded_size,
        expires_at: body.expires_at,
        height: body.height,
        media_type: body.media_type,
        retention_status: body.retention_status,
        width: body.width,
      };
      renderServerMetadata(authoritativeMetadata);
      clearCapturedFrame();
      setState(
        "submitted_ephemeral",
        "Temporary server frame created. It expires after 15 minutes and is not analyzed.",
        false
      );
    } catch (_error) {
      enterAuthorityStale(
        "Submission result is unknown. Reload the page. Any accepted temporary frame will expire automatically.",
        true
      );
    } finally {
      modifyingRequestInFlight = false;
      updateControls();
    }
  }

  function proposalResultUnknown() {
    enterAuthorityStale(
      "Proposal result is unknown. Reload the page. The temporary session will expire automatically.",
      false
    );
  }

  async function createProposal() {
    if (
      state !== "selecting_goal" ||
      !hasPrivateServerSession() ||
      !hasCurrentCsrfAuthority() ||
      !hasValidProposalSelection() ||
      modifyingRequestInFlight ||
      destroyed ||
      privateProposal
    ) {
      return;
    }

    const sessionId = privateSessionId;
    const capability = privateSessionCapability;
    const goal = proposalGoal.value;
    const userContext = normalizedProposalContext(proposalContext.value);
    if (userContext === null) {
      setState("proposal_failed", messages.camera_proposal_context_invalid, true);
      return;
    }
    modifyingRequestInFlight = true;
    setState("proposing", "Creating an inert temporary proposal...", false);
    try {
      const response = await fetch(
        SESSION_ENDPOINT + "/" + encodeURIComponent(sessionId) + PROPOSAL_ENDPOINT_SUFFIX,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            [CSRF_REQUEST_HEADER]: csrfToken,
            [CAPABILITY_HEADER]: capability,
          },
          body: JSON.stringify({ goal: goal, user_context: userContext }),
          credentials: "same-origin",
          cache: "no-store",
          redirect: "error",
        }
      );
      if (!rotateCsrfAuthority(response)) {
        proposalResultUnknown();
        return;
      }
      if (response.status !== 201 || !isApprovedJsonResponse(response)) {
        if (response.status === 201) {
          proposalResultUnknown();
          return;
        }
        const code = await boundedErrorCode(response);
        if (code === "camera_proposal_already_exists" || code === "camera_session_not_found") {
          proposalResultUnknown();
          return;
        }
        setState("proposal_failed", code + ": " + messages[code], true);
        return;
      }
      let body;
      try {
        body = await response.json();
      } catch (_error) {
        proposalResultUnknown();
        return;
      }
      if (!isApprovedProposalResponse(body, goal, userContext)) {
        proposalResultUnknown();
        return;
      }
      privateProposal = body;
      renderProposal(privateProposal);
      setState("proposal_created", "Temporary inert proposal created. No image analysis or action occurred.", false);
    } catch (_error) {
      proposalResultUnknown();
    } finally {
      modifyingRequestInFlight = false;
      updateControls();
    }
  }

  async function discardTemporaryServerFrame() {
    if (
      !["submitted_ephemeral", "selecting_goal", "proposal_created", "proposal_failed"].includes(state) ||
      !hasPrivateServerSession() ||
      !hasCurrentCsrfAuthority() ||
      modifyingRequestInFlight ||
      destroyed
    ) {
      return;
    }

    const sessionId = privateSessionId;
    const capability = privateSessionCapability;
    const priorState = state;
    modifyingRequestInFlight = true;
    setState("discarding_server", "Discarding the temporary server frame...", false);
    try {
      const response = await fetch(SESSION_ENDPOINT + "/" + encodeURIComponent(sessionId), {
        method: "DELETE",
        headers: {
          [CSRF_REQUEST_HEADER]: csrfToken,
          [CAPABILITY_HEADER]: capability,
        },
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
      });
      if (!rotateCsrfAuthority(response)) {
        enterAuthorityStale(
          "Discard result is unknown. Reload the page. Expiry cleanup remains the safety fallback.",
          false
        );
        return;
      }
      if (response.status === 204) {
        let responseBody = "";
        try {
          responseBody = await response.text();
        } catch (_error) {
          enterAuthorityStale(
            "Discard result is unknown. Reload the page. Expiry cleanup remains the safety fallback.",
            false
          );
          return;
        }
        if (responseBody !== "") {
          enterAuthorityStale(
            "Discard result is unknown. Reload the page. Expiry cleanup remains the safety fallback.",
            false
          );
          return;
        }
        clearServerSession();
        setState("idle", "The temporary frame and proposal were discarded.", false);
        return;
      }
      const code = await boundedErrorCode(response);
      if (code === "camera_session_not_found") {
        clearServerSession();
        setState(
          "idle",
          "The temporary server frame is no longer controllable. Reload before starting a new workflow.",
          true
        );
        return;
      }
      if (code === "deletion_failed") {
        setState(priorState, code + ": " + messages[code], true);
        return;
      }
      enterAuthorityStale(
        "Discard result is unknown. Reload the page. Expiry cleanup remains the safety fallback.",
        false
      );
    } catch (_error) {
      enterAuthorityStale(
        "Discard result is unknown. Reload the page. Expiry cleanup remains the safety fallback.",
        false
      );
    } finally {
      modifyingRequestInFlight = false;
      updateControls();
    }
  }

  async function switchCamera(deviceId) {
    if (state !== "active" || !deviceId || deviceId === selectedDeviceId) {
      return;
    }
    state = "stopping";
    clearPreview(false);
    state = "idle";
    await startCamera(deviceId);
  }

  async function retakeFrame() {
    if (state !== "captured" || hasPrivateServerSession() || modifyingRequestInFlight) {
      return;
    }
    const deviceId = selectedDeviceId;
    clearCapturedFrame();
    setState("idle", "Captured frame cleared. Requesting camera for a retake...", false);
    await startCamera(deviceId);
  }

  function discardFrame() {
    if (state !== "captured" || hasPrivateServerSession() || modifyingRequestInFlight) {
      return;
    }
    captureGeneration += 1;
    clearCapturedFrame();
    clearPreview(true);
    setState("idle", "Captured frame discarded. Camera is inactive.", false);
  }

  function teardownForNavigation() {
    captureGeneration += 1;
    modifyingRequestInFlight = false;
    clearPreview(true);
    clearCapturedFrame();
    clearServerSession();
    clearCsrfAuthority();
  }

  enableButton.addEventListener("click", function () {
    void startCamera("");
  });

  stopButton.addEventListener("click", function () {
    stopCamera("Camera stopped.");
  });

  captureButton.addEventListener("click", function () {
    void captureFrame();
  });

  retakeButton.addEventListener("click", function () {
    void retakeFrame();
  });

  discardButton.addEventListener("click", function () {
    discardFrame();
  });

  createSessionButton.addEventListener("click", function () {
    void createTemporarySession();
  });

  proposalGoal.addEventListener("change", function () {
    if (!hasPrivateServerSession() || !hasCurrentCsrfAuthority() || privateProposal || destroyed) {
      return;
    }
    if (PROPOSAL_GOALS.includes(proposalGoal.value)) {
      setState("selecting_goal", "Select optional context, then create one inert temporary proposal.", false);
    } else {
      setState("submitted_ephemeral", "Select one creation goal before creating a proposal.", false);
    }
  });

  proposalContext.addEventListener("input", function () {
    if (state === "proposal_failed" && hasPrivateServerSession() && !privateProposal) {
      setState("selecting_goal", "Select optional context, then create one inert temporary proposal.", false);
      return;
    }
    updateControls();
  });

  createProposalButton.addEventListener("click", function () {
    void createProposal();
  });

  serverDiscardButton.addEventListener("click", function () {
    void discardTemporaryServerFrame();
  });

  deviceSelect.addEventListener("change", function () {
    void switchCamera(deviceSelect.value);
  });

  window.addEventListener("pagehide", function () {
    destroyed = true;
    teardownForNavigation();
    setState("idle", "Camera and temporary authority cleared for navigation.", false);
  });

  window.addEventListener("pageshow", function (event) {
    if (event.persisted === true) {
      destroyed = true;
      teardownForNavigation();
      setState("authority_stale", "Reload required before camera submission can continue.", true);
      return;
    }
    destroyed = false;
    updateControls();
  });

  supportStatus.textContent = mediaApiAvailable()
    ? "Camera preview and one-frame capture are supported. Camera is inactive."
    : "Camera preview is unavailable in this secure browser context.";
  clearCapturedFrame();
  clearServerSession();
  if (captureInitialCsrfAuthority()) {
    setState("idle", "Camera is inactive. No frame is held in memory.", false);
  } else {
    setState("authority_stale", "Reload required before camera submission can continue.", true);
  }
})();
