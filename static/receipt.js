(() => {
  function findOption(input) {
    const listId = input.getAttribute("list");
    const list = listId ? document.getElementById(listId) : null;
    if (!list) {
      return null;
    }

    const value = input.value.trim().toLocaleLowerCase();
    return Array.from(list.options).find(
      (option) => option.value.trim().toLocaleLowerCase() === value
    );
  }

  function syncCard(card) {
    const nameInput = card.querySelector("[data-receipt-prior-name]");
    const idInput = card.querySelector("[data-receipt-prior-id]");
    const quantityInput = card.querySelector("[data-receipt-quantity]");
    const unitInput = card.querySelector("[data-receipt-unit]");
    const locationInput = card.querySelector("[data-receipt-location]");
    if (!nameInput || !idInput) {
      return;
    }

    const option = findOption(nameInput);
    if (!option) {
      idInput.value = "";
      return;
    }

    idInput.value = option.dataset.id || "";
    if (quantityInput && option.dataset.typicalQuantity) {
      quantityInput.value = option.dataset.typicalQuantity;
    }
    if (unitInput && option.dataset.typicalUnit) {
      unitInput.value = option.dataset.typicalUnit;
    }
    if (locationInput && option.dataset.defaultLocation) {
      locationInput.value = option.dataset.defaultLocation;
    }
  }

  document.querySelectorAll("[data-receipt-card]").forEach((card) => {
    const nameInput = card.querySelector("[data-receipt-prior-name]");
    if (nameInput) {
      nameInput.addEventListener("input", () => syncCard(card));
      nameInput.addEventListener("change", () => syncCard(card));
    }

    const removeButton = card.querySelector("[data-remove-card]");
    if (removeButton) {
      removeButton.addEventListener("click", () => {
        card.querySelectorAll("input, select, textarea, button").forEach((field) => {
          if (field !== removeButton) {
            field.disabled = true;
          }
        });
        card.remove();
      });
    }
  });
})();
