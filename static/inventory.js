(() => {
  const SORT_KEY = "kitchen-planner.inventory.sort";
  const POSITION_KEY = "kitchen-planner.inventory.position";

  const container = document.querySelector("[data-inventory-container]");
  if (!container) return;

  const listPanel = container.closest("[data-inventory-location]");
  const context = listPanel
    ? `${listPanel.dataset.inventoryLocation || "all"}:${listPanel.dataset.inventoryView || "grid"}`
    : "all:grid";

  const sortSelect = document.querySelector("[data-inventory-sort-select]");
  const searchInput = document.querySelector("[data-inventory-search]");

  // ── Sorting ────────────────────────────────────────────────────────────────

  function getItems() {
    return Array.from(container.children);
  }

  function applySort(by) {
    window.localStorage.setItem(SORT_KEY, by);

    if (sortSelect && sortSelect.value !== by) sortSelect.value = by;

    const items = getItems();
    items.sort((a, b) => {
      if (by === "created") {
        const ca = a.dataset.created || "";
        const cb = b.dataset.created || "";
        return ca.localeCompare(cb) || (a.dataset.name || "").localeCompare(b.dataset.name || "");
      }
      if (by === "name") {
        return (a.dataset.name || "").localeCompare(b.dataset.name || "");
      }
      // Default: expiry (empty = no expiry → sort last)
      const noA = !a.dataset.expiry;
      const noB = !b.dataset.expiry;
      if (noA !== noB) return noA ? 1 : -1;
      return (a.dataset.expiry || "").localeCompare(b.dataset.expiry || "") ||
        (a.dataset.name || "").localeCompare(b.dataset.name || "");
    });

    items.forEach((item) => container.appendChild(item));
  }

  if (sortSelect) {
    sortSelect.addEventListener("change", () => applySort(sortSelect.value));
  }

  // Custom-styled dropdown to replace native popup
  function initCustomSortSelect() {
    const native = document.querySelector("[data-inventory-sort-select]");
    if (!native) return;
    const wrapper = native.closest('.sort-select-wrap');
    if (!wrapper) return;
    const custom = wrapper.querySelector('[data-custom-select]');
    const trigger = custom && custom.querySelector('.custom-select-trigger');
    const list = custom && custom.querySelector('.custom-select-list');

    // populate list from native options
    Array.from(native.options).forEach((opt) => {
      const li = document.createElement('li');
      li.className = 'custom-select-item';
      li.setAttribute('role', 'option');
      li.dataset.value = opt.value;
      li.textContent = opt.textContent;
      list.appendChild(li);
    });

    function close() {
      custom.querySelector('.custom-select-list').hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
    }
    function open() {
      custom.querySelector('.custom-select-list').hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
      list.focus();
    }

    trigger.addEventListener('click', (e) => {
      const openNow = !list.hidden;
      if (openNow) {
        close();
      } else {
        open();
      }
    });

    list.addEventListener('click', (e) => {
      const item = e.target.closest('.custom-select-item');
      if (!item) return;
      native.value = item.dataset.value;
      trigger.querySelector('.custom-select-value').textContent = item.textContent;
      applySort(native.value);
      close();
    });

    document.addEventListener('click', (e) => {
      if (!wrapper.contains(e.target)) close();
    });

    // sync initial label
    const init = native.value || native.options[0].value;
    const initText = native.querySelector(`option[value="${init}"]`).textContent;
    trigger.querySelector('.custom-select-value').textContent = initText;
  }

  initCustomSortSelect();

  // ── Search / Filter ────────────────────────────────────────────────────────

  function applyFilter(query) {
    const needle = query.trim().toLowerCase();
    getItems().forEach((item) => {
      const name = (item.dataset.name || "").toLowerCase();
      const cat = (item.dataset.category || "").toLowerCase();
      item.hidden = needle !== "" && !name.includes(needle) && !cat.includes(needle);
    });
  }

  if (searchInput) {
    searchInput.addEventListener("input", () => applyFilter(searchInput.value));
  }

  // Cotto/Aperto: detach the selected amount into a new refrigerated item.
  const preparationDialog = document.querySelector("[data-preparation-dialog]");
  if (preparationDialog) {
    const form = preparationDialog.querySelector("[data-preparation-form]");
    const description = preparationDialog.querySelector("[data-preparation-description]");
    const quantity = preparationDialog.querySelector("[data-preparation-quantity]");
    document.querySelectorAll("[data-open-preparation]").forEach((button) => {
      button.addEventListener("click", () => {
        const max = button.dataset.itemQuantity;
        form.action = `/inventory/${button.dataset.itemId}/prepare?location=${encodeURIComponent(listPanel?.dataset.inventoryLocation || "")}&view=${encodeURIComponent(listPanel?.dataset.inventoryView || "")}`;
        description.textContent = `${button.dataset.itemName}: scegli quanto trasformare (disponibile ${max} ${button.dataset.itemUnit}).`;
        quantity.value = max;
        quantity.max = max;
        preparationDialog.showModal();
      });
    });
    preparationDialog.querySelector("[data-preparation-cancel]").addEventListener("click", () => preparationDialog.close());
    preparationDialog.addEventListener("click", (event) => { if (event.target === preparationDialog) preparationDialog.close(); });
  }

  // Modifica rapida della quantità visualizzata. Nell'inventario l'unità non
  // è modificabile dal popup: deriva dalla modalità scelta per il prodotto.
  const quantityDialog = document.querySelector("[data-quantity-dialog]");
  const quantityForm = quantityDialog?.querySelector("[data-quantity-edit-form]");
  if (quantityDialog && quantityForm) {
    let editingTrigger = null;
    const unitWrap = quantityForm.querySelector("[data-edit-unit-wrap]");
    const unitInput = quantityForm.querySelector("[data-edit-unit-input]");
    document.querySelectorAll("[data-edit-quantity][data-edit-inventory]").forEach((trigger) => {
      trigger.addEventListener("click", () => {
        editingTrigger = trigger;
        quantityForm.elements.quantity.value = trigger.dataset.itemQuantity;
        unitInput.value = trigger.dataset.itemUnit;
        unitWrap.hidden = true;
        quantityForm.querySelector("[data-edit-item-name]").textContent = trigger.dataset.itemName;
        quantityForm.querySelector("[data-edit-error]").hidden = true;
        quantityDialog.showModal();
        quantityForm.elements.quantity.focus();
        quantityForm.elements.quantity.select();
      });
    });
    quantityForm.querySelector("[data-edit-cancel]")?.addEventListener("click", () => quantityDialog.close());
    quantityForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!editingTrigger) return;
      const error = quantityForm.querySelector("[data-edit-error]");
      const body = new FormData(quantityForm);
      body.append("direction", "edit");
      try {
        const response = await fetch(`/inventory/${editingTrigger.dataset.itemId}/adjust`, {
          method: "POST", headers: { "X-Requested-With": "XMLHttpRequest" }, body,
        });
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || "Salvataggio non riuscito.");
        editingTrigger.textContent = data.qty_display;
        editingTrigger.dataset.itemQuantity = data.quantity;
        editingTrigger.dataset.itemUnit = data.unit;
        const change = editingTrigger.closest(".item-main")?.querySelector("[data-today-quantity-change]");
        if (change) {
          const amount = Number(data.today_quantity_change || 0);
          change.hidden = !amount;
          change.classList.toggle("is-added", amount > 0);
          change.classList.toggle("is-used", amount < 0);
          change.innerHTML = `<span aria-hidden="true">${amount > 0 ? "▲" : "▼"}</span> ${data.today_quantity_change_display || Math.abs(amount)}`;
        }
        quantityDialog.close();
      } catch (err) {
        error.textContent = err.message;
        error.hidden = false;
      }
    });
  }

  // Finishing or deleting reloads the page. Keep the viewport at the same
  // point in the current section instead of jumping back to the top.
  document.querySelectorAll("[data-inventory-navigation]").forEach((form) => {
    form.addEventListener("submit", () => {
      window.sessionStorage.setItem(
        `${POSITION_KEY}:${context}`,
        String(window.scrollY),
      );
    });
  });

  // ── Init ──────────────────────────────────────────────────────────────────

  const savedSort = window.localStorage.getItem(SORT_KEY) || "expiry";
  applySort(savedSort);

  const savedPosition = window.sessionStorage.getItem(`${POSITION_KEY}:${context}`);
  if (savedPosition !== null) {
    window.sessionStorage.removeItem(`${POSITION_KEY}:${context}`);
    const position = Number.parseInt(savedPosition, 10);
    if (Number.isFinite(position)) {
      window.requestAnimationFrame(() => window.scrollTo(0, position));
    }
  }
})();
