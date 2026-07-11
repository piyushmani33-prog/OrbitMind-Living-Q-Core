(function () {
  "use strict";

  const dataNode = document.getElementById("trajectory-replay-data");
  const marker = document.getElementById("satellite-marker");
  const slider = document.getElementById("replay-slider");
  const playButton = document.getElementById("replay-play");
  const previousButton = document.getElementById("replay-prev");
  const nextButton = document.getElementById("replay-next");
  const speedSelect = document.getElementById("replay-speed");
  const errorBox = document.getElementById("trajectory-replay-error");
  const values = Array.from(document.querySelectorAll(".readout-grid .metric-value"));
  if (
    !dataNode || !marker || !slider || !playButton || !previousButton ||
    !nextButton || !speedSelect || !errorBox
  ) {
    return;
  }

  let payload;
  let sampleIndex = 0;
  let playing = false;
  let startedAt = 0;
  const baseMs = 30000;

  function fail() {
    playing = false;
    playButton.disabled = true;
    previousButton.disabled = true;
    nextButton.disabled = true;
    slider.disabled = true;
    speedSelect.disabled = true;
    errorBox.style.display = "block";
  }

  function isGoodSample(sample, index) {
    return sample && sample.sequence === index && Number.isFinite(sample.x) &&
      Number.isFinite(sample.y) && typeof sample.timestamp_utc === "string" &&
      Number.isFinite(sample.latitude_deg) && Number.isFinite(sample.longitude_deg) &&
      Number.isFinite(sample.altitude_km);
  }

  function setValue(index, value) {
    if (values[index]) {
      values[index].textContent = value;
    }
  }

  function payloadText(node) {
    if (node.tagName === "TEMPLATE" && node.content) {
      return node.content.textContent;
    }
    return node.textContent;
  }

  function show(index) {
    const sample = payload.samples[index];
    if (!isGoodSample(sample, index)) {
      fail();
      return;
    }
    sampleIndex = index;
    marker.setAttribute("cx", String(sample.x));
    marker.setAttribute("cy", String(sample.y));
    slider.value = String(index);
    slider.setAttribute("aria-valuenow", String(index + 1));
    slider.setAttribute(
      "aria-valuetext",
      "Sample " + String(index + 1) + " of " + String(payload.sample_count),
    );
    setValue(0, String(index + 1) + " of " + String(payload.sample_count));
    setValue(1, sample.timestamp_utc.replace("T", " ").replace("Z", " UTC"));
    setValue(2, sample.latitude_deg.toFixed(4) + "°");
    setValue(3, sample.longitude_deg.toFixed(4) + "°");
    setValue(4, sample.altitude_km.toFixed(3) + " km");
    if (Object.prototype.hasOwnProperty.call(sample, "azimuth_deg")) {
      setValue(5, sample.azimuth_deg.toFixed(2) + "°");
      setValue(6, sample.elevation_deg.toFixed(2) + "°");
      setValue(7, sample.range_km.toFixed(2) + " km");
    }
  }

  function setPlaying(next) {
    playing = next;
    playButton.textContent = playing ? "Pause" : "Play";
    playButton.setAttribute("aria-pressed", playing ? "true" : "false");
    if (playing) {
      startedAt = performance.now() - (sampleIndex / Math.max(payload.sample_count - 1, 1)) *
        baseMs / Number(speedSelect.value);
      requestAnimationFrame(tick);
    }
  }

  function tick(now) {
    if (!playing) {
      return;
    }
    const speed = Number(speedSelect.value);
    const progress = Math.min((now - startedAt) / (baseMs / speed), 1);
    const nextIndex = Math.round(progress * (payload.sample_count - 1));
    show(nextIndex);
    if (progress >= 1) {
      setPlaying(false);
      return;
    }
    requestAnimationFrame(tick);
  }

  try {
    payload = JSON.parse(payloadText(dataNode));
    if (!payload || payload.schema_version !== "trajectory-replay-display-v1" ||
        !Array.isArray(payload.samples) || payload.samples.length !== payload.sample_count ||
        payload.sample_count < 2) {
      fail();
      return;
    }
    for (let index = 0; index < payload.samples.length; index += 1) {
      if (!isGoodSample(payload.samples[index], index)) {
        fail();
        return;
      }
    }
  } catch {
    fail();
    return;
  }

  playButton.addEventListener("click", function () {
    if (!playing && sampleIndex === payload.sample_count - 1) {
      show(0);
    }
    setPlaying(!playing);
  });
  previousButton.addEventListener("click", function () {
    setPlaying(false);
    show(Math.max(sampleIndex - 1, 0));
  });
  nextButton.addEventListener("click", function () {
    setPlaying(false);
    show(Math.min(sampleIndex + 1, payload.sample_count - 1));
  });
  slider.addEventListener("input", function () {
    setPlaying(false);
    show(Number(slider.value));
  });
  speedSelect.addEventListener("change", function () {
    if (playing) {
      setPlaying(false);
    }
  });
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    setPlaying(false);
  }
  show(0);
}());
