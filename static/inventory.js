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
