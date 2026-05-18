(() => {
  function normalizeUnit(value) {
    return (value || "").trim().toLocaleLowerCase();
  }

  function stepForUnit(unit) {
    const normalized = normalizeUnit(unit);
    if (["pz", "pc", "pezzo", "pezzi", "unita", "u"].includes(normalized)) {
      return 1;
    }
    if (["g", "gr", "grammo", "grammi", "ml"].includes(normalized)) {
      return 100;
    }
    if (["kg", "l", "lt"].includes(normalized)) {
      return 1;
    }
    return 1;
  }

  function decimals(step) {
    const str = String(step);
    const dotIndex = str.indexOf(".");
    return dotIndex === -1 ? 0 : str.length - dotIndex - 1;
  }

  function parseNumber(value, fallback = 0) {
    const parsed = Number.parseFloat(String(value).replace(",", "."));
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function roundToStep(value, step) {
    const places = Math.max(2, decimals(step));
    return Number.parseFloat(value.toFixed(places));
  }

  function resolveStep(input, unitField) {
    const fromUnit = stepForUnit(unitField ? unitField.value : "");
    const minStep = parseNumber(input.getAttribute("min"), 0.01);
    return Math.max(fromUnit, minStep);
  }

  function updateInputStep(input, unitField) {
    input.step = String(resolveStep(input, unitField));
  }

  function bindControl(control) {
    const input = control.querySelector("[data-qty-input]");
    if (!input) {
      return;
    }

    const unitSelector = control.getAttribute("data-qty-unit-selector") || "";
    const host = control.closest("form") || control.parentElement || document;
    const unitField = unitSelector ? host.querySelector(unitSelector) : null;
    const decrease = control.querySelector("[data-qty-action='decrease']");
    const increase = control.querySelector("[data-qty-action='increase']");

    function apply(action) {
      const current = parseNumber(input.value, parseNumber(input.min, 1));
      const step = resolveStep(input, unitField);
      const minValue = parseNumber(input.min, 0.01);
      const delta = action === "increase" ? step : -step;
      const next = Math.max(minValue, roundToStep(current + delta, step));
      input.value = String(next);
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }

    if (decrease) {
      decrease.addEventListener("click", () => apply("decrease"));
    }
    if (increase) {
      increase.addEventListener("click", () => apply("increase"));
    }

    if (unitField) {
      unitField.addEventListener("input", () => updateInputStep(input, unitField));
      unitField.addEventListener("change", () => updateInputStep(input, unitField));
    }

    updateInputStep(input, unitField);
  }

  document.querySelectorAll("[data-qty-control]").forEach(bindControl);
})();
