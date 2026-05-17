(() => {
  const mappings = {
    quantity: "typicalQuantity",
    unit: "typicalUnit",
    location: "defaultLocation",
    target_location: "defaultLocation",
  };

  function addDays(dateValue, days) {
    if (!dateValue || !days) {
      return "";
    }
    const date = new Date(`${dateValue}T00:00:00`);
    date.setDate(date.getDate() + Number.parseInt(days, 10));
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

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

  function setField(form, name, value) {
    const field = form.querySelector(`[data-prior-field="${name}"]`);
    if (!field) {
      return;
    }

    if (value) {
      field.value = value;
      field.dataset.priorAutofilled = "1";
      return;
    }

    if (field.dataset.priorAutofilled === "1") {
      field.value = "";
      field.dataset.priorAutofilled = "";
    }
  }

  function syncPrior(form) {
    const input = form.querySelector("[data-prior-name]");
    const idInput = form.querySelector("[data-prior-id]");
    if (!input || !idInput) {
      return;
    }

    const option = findOption(input);
    if (!option) {
      idInput.value = "";
      return;
    }

    idInput.value = option.dataset.id || "";
    Object.entries(mappings).forEach(([fieldName, dataKey]) => {
      setField(form, fieldName, option.dataset[dataKey] || "");
    });

    const expiryField = form.querySelector("[data-prior-expiry]");
    const expiryEstimatedField = form.querySelector("[data-prior-expiry-estimated]");
    const shelfLifeDays = option.dataset.typicalShelfLifeDays || "";
    if (expiryField && shelfLifeDays) {
      const defaultExpiry = addDays(form.dataset.today, shelfLifeDays);
      if (defaultExpiry && (!expiryField.value || expiryField.dataset.priorAutofilled === "1")) {
        expiryField.value = defaultExpiry;
        expiryField.dataset.priorAutofilled = "1";
        if (expiryEstimatedField) {
          expiryEstimatedField.value = "1";
        }
      }
    }
  }

  document.querySelectorAll("[data-prior-picker]").forEach((form) => {
    const input = form.querySelector("[data-prior-name]");
    if (!input) {
      return;
    }

    input.addEventListener("input", () => syncPrior(form));
    input.addEventListener("change", () => syncPrior(form));
    const expiryField = form.querySelector("[data-prior-expiry]");
    const expiryEstimatedField = form.querySelector("[data-prior-expiry-estimated]");
    if (expiryField && expiryEstimatedField) {
      expiryField.addEventListener("input", () => {
        expiryField.dataset.priorAutofilled = "";
        expiryEstimatedField.value = "0";
      });
    }
    syncPrior(form);
  });
})();
