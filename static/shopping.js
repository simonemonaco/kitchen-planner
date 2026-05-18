(() => {
  const MODE_KEY = "kitchen-planner.shopping.mode";
  const SELECTION_KEY = "kitchen-planner.shopping.selection";

  const layout = document.querySelector("[data-shopping-layout]");
  if (!layout) {
    return;
  }

  const modeToggle = document.querySelector("[data-shopping-mode-toggle]");
  const checkboxes = Array.from(document.querySelectorAll("[data-shopping-select]"));
  const completeForm = document.querySelector("[data-shopping-complete-form]");
  const selectedInputsHost = document.querySelector("[data-shopping-selected-inputs]");
  const status = document.querySelector("[data-shopping-selection-status]");
  const completeButton = document.querySelector("[data-shopping-complete-button]");

  function readSelection() {
    try {
      const raw = window.localStorage.getItem(SELECTION_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed.map(String) : [];
    } catch {
      return [];
    }
  }

  function writeSelection(values) {
    window.localStorage.setItem(SELECTION_KEY, JSON.stringify(values));
  }

  function currentItemIds() {
    return checkboxes.map((checkbox) => checkbox.value);
  }

  function syncStoredSelection() {
    const available = new Set(currentItemIds());
    const filtered = readSelection().filter((value) => available.has(value));
    writeSelection(filtered);
    return new Set(filtered);
  }

  function renderSelectedInputs(selectedValues) {
    if (!selectedInputsHost) {
      return;
    }

    selectedInputsHost.innerHTML = "";
    selectedValues.forEach((value) => {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = "selected_ids";
      input.value = value;
      selectedInputsHost.appendChild(input);
    });
  }

  function updateSelectionUI() {
    const selectedValues = checkboxes.filter((checkbox) => checkbox.checked).map((checkbox) => checkbox.value);
    const totalCount = checkboxes.length;
    writeSelection(selectedValues);
    renderSelectedInputs(selectedValues);

    if (status) {
      status.textContent = `${selectedValues.length}/${totalCount} prodotti selezionati`;
    }
    if (completeButton) {
      completeButton.disabled = selectedValues.length === 0;
    }
  }

  function applyStoredSelection() {
    const selected = syncStoredSelection();
    checkboxes.forEach((checkbox) => {
      checkbox.checked = selected.has(checkbox.value);
    });
    updateSelectionUI();
  }

  function applyMode(mode) {
    const resolvedMode = mode === "spesa" ? "spesa" : "inserimento";
    layout.classList.toggle("is-shopping-mode", resolvedMode === "spesa");
    if (modeToggle) {
      modeToggle.checked = resolvedMode === "spesa";
    }
    window.localStorage.setItem(MODE_KEY, resolvedMode);
  }

  if (modeToggle) {
    modeToggle.addEventListener("change", () => applyMode(modeToggle.checked ? "spesa" : "inserimento"));
  }

  checkboxes.forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      updateSelectionUI();
      updateCardSelection();
    });
  });

  function updateCardSelection() {
    const selected = new Set(checkboxes.filter((cb) => cb.checked).map((cb) => cb.value));
    checkboxes.forEach((checkbox) => {
      const card = checkbox.closest(".shopping-row");
      if (card) {
        card.classList.toggle("is-selected", selected.has(checkbox.value));
      }
    });
  }

  if (completeForm) {
    completeForm.addEventListener("submit", () => {
      const selectedValues = checkboxes.filter((checkbox) => checkbox.checked).map((checkbox) => checkbox.value);
      renderSelectedInputs(selectedValues);
    });
  }

  applyMode(window.localStorage.getItem(MODE_KEY) || "inserimento");
  applyStoredSelection();
  updateCardSelection();
})();
