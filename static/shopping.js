(() => {
  const SELECTION_KEY = "kitchen-planner.shopping.selection";

  const layout = document.querySelector("[data-shopping-layout]");
  if (!layout) {
    return;
  }

  const checkboxes = Array.from(document.querySelectorAll("[data-shopping-select]"));
  const completeForm = document.querySelector("[data-shopping-complete-form]");
  const selectedInputsHost = document.querySelector("[data-shopping-selected-inputs]");
  const status = document.querySelector("[data-shopping-selection-status]");
  const completeButton = document.querySelector("[data-shopping-complete-button]");
  const quantityDialog = document.querySelector("[data-quantity-dialog]");
  const quantityForm = document.querySelector("[data-quantity-edit-form]");
  let editingTrigger = null;

  document.querySelectorAll("[data-edit-quantity]").forEach((trigger) => {
    trigger.addEventListener("click", () => {
      editingTrigger = trigger;
      quantityForm.elements.quantity.value = trigger.dataset.itemQuantity;
      quantityForm.elements.unit.value = trigger.dataset.itemUnit;
      quantityForm.querySelector("[data-edit-item-name]").textContent = trigger.dataset.itemName;
      quantityForm.querySelector("[data-edit-error]").hidden = true;
      quantityDialog.showModal();
      quantityForm.elements.quantity.focus();
      quantityForm.elements.quantity.select();
    });
  });
  quantityForm?.querySelector("[data-edit-cancel]")?.addEventListener("click", () => quantityDialog.close());
  quantityForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const error = quantityForm.querySelector("[data-edit-error]");
    const body = new FormData(quantityForm);
    body.append("direction", "edit");
    try {
      const response = await fetch(`/shopping/${editingTrigger.dataset.itemId}/adjust`, {
        method: "POST", headers: { "X-Requested-With": "XMLHttpRequest" }, body,
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || "Salvataggio non riuscito.");
      editingTrigger.textContent = data.qty_display;
      editingTrigger.dataset.itemQuantity = data.quantity;
      editingTrigger.dataset.itemUnit = data.unit;
      quantityDialog.close();
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
    }
  });

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

  applyStoredSelection();
  updateCardSelection();
})();
