(function () {
  "use strict";

  var dataNode = document.getElementById("laboratory-data");
  var focusSection = document.getElementById("laboratory-focus");
  var statusLine = document.getElementById("lab-focus-status");
  var buttons = Array.prototype.slice.call(document.querySelectorAll("button.lab-select"));
  var nodes = Array.prototype.slice.call(document.querySelectorAll("a.lab-node"));
  var panels = Array.prototype.slice.call(document.querySelectorAll("article.lab-panel"));
  if (!dataNode || !focusSection || !statusLine || buttons.length === 0 || panels.length === 0) {
    return;
  }

  function payloadText(node) {
    if (node.tagName === "TEMPLATE" && node.content) {
      return node.content.textContent;
    }
    return node.textContent;
  }

  var payload;
  try {
    payload = JSON.parse(payloadText(dataNode));
  } catch (error) {
    return;
  }
  if (!payload || payload.schema_version !== "laboratory-catalog-v1" ||
      !Array.isArray(payload.laboratories) || !Array.isArray(payload.planned_laboratories)) {
    return;
  }

  // Truthfulness guard: the server-rendered panels must match the registry
  // payload exactly. On any mismatch, do not enhance — leave every record
  // visible instead of showing a filtered (possibly wrong) view.
  var payloadIds = payload.laboratories.map(function (laboratory) {
    return laboratory.laboratory_id;
  }).concat(payload.planned_laboratories.map(function (planned) {
    return planned.laboratory_id;
  })).sort();
  var panelIds = panels.map(function (panel) {
    return panel.id.replace("lab-panel-", "");
  }).sort();
  if (payloadIds.length !== panelIds.length) {
    return;
  }
  for (var index = 0; index < payloadIds.length; index += 1) {
    if (payloadIds[index] !== panelIds[index]) {
      return;
    }
  }

  var reducedMotion = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function displayName(labId) {
    var everything = payload.laboratories.concat(payload.planned_laboratories);
    for (var i = 0; i < everything.length; i += 1) {
      if (everything[i].laboratory_id === labId) {
        return everything[i].display_name;
      }
    }
    return labId;
  }

  function select(labId, moveFocus) {
    panels.forEach(function (panel) {
      var selected = panel.id === "lab-panel-" + labId;
      if (selected) {
        panel.removeAttribute("hidden");
      } else {
        panel.setAttribute("hidden", "hidden");
      }
    });
    buttons.forEach(function (button) {
      button.setAttribute("aria-pressed", button.dataset.lab === labId ? "true" : "false");
    });
    nodes.forEach(function (node) {
      if (node.dataset.lab === labId) {
        node.setAttribute("data-selected", "true");
      } else {
        node.removeAttribute("data-selected");
      }
    });
    statusLine.textContent = "Showing: " + displayName(labId) +
      " (selection is local and read-only)";
    if (moveFocus) {
      var target = document.getElementById("lab-panel-" + labId);
      if (target) {
        target.focus({ preventScroll: true });
        target.scrollIntoView({
          behavior: reducedMotion ? "auto" : "smooth",
          block: "nearest"
        });
      }
    }
  }

  buttons.forEach(function (button) {
    button.addEventListener("click", function () {
      select(button.dataset.lab, true);
    });
  });
  nodes.forEach(function (node) {
    node.addEventListener("click", function (event) {
      event.preventDefault();
      select(node.dataset.lab, true);
    });
  });

  focusSection.classList.add("js-enhanced");
  var first = payload.laboratories.length > 0 ?
    payload.laboratories[0].laboratory_id :
    payload.planned_laboratories[0].laboratory_id;
  select(first, false);
}());
