(() => {
  function setupAutocomplete(input, list) {
    if (input.dataset.autocompleteReady === "1") {
      return;
    }
    const options = Array.from(list.options).filter((option) => option.value.trim());
    if (!options.some((option) => option.dataset.id || option.dataset.recipeId)) {
      return;
    }
    input.dataset.autocompleteReady = "1";
    input.dataset.autocompleteSource = input.getAttribute("list");

    const wrapper = document.createElement("div");
    wrapper.className = "autocomplete-field";
    input.parentNode.insertBefore(wrapper, input);
    wrapper.appendChild(input);
    input.removeAttribute("list");

    const menu = document.createElement("div");
    menu.className = "autocomplete-menu";
    menu.setAttribute("role", "listbox");
    menu.hidden = true;
    wrapper.appendChild(menu);

    let activeIndex = -1;

    function close() {
      menu.hidden = true;
      activeIndex = -1;
    }

    function choose(option) {
      input.value = option.value;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      close();
    }

    function render() {
      const query = input.value.trim().toLocaleLowerCase();
      if (query.length < 3) {
        menu.replaceChildren();
        close();
        return;
      }
      const matches = options.filter((option) => option.value.toLocaleLowerCase().includes(query)).slice(0, 8);
      menu.replaceChildren();
      activeIndex = -1;
      if (!matches.length || document.activeElement !== input) {
        close();
        return;
      }

      matches.forEach((option, index) => {
        const item = document.createElement("button");
        item.type = "button";
        item.className = "autocomplete-option";
        item.setAttribute("role", "option");
        item.dataset.index = String(index);

        const media = document.createElement("span");
        media.className = "autocomplete-option-media";
        if (option.dataset.picture) {
          const image = document.createElement("img");
          image.src = option.dataset.picture;
          image.alt = "";
          image.addEventListener("error", () => {
            media.replaceChildren();
            media.innerHTML = '<i class="fa-solid fa-box" aria-hidden="true"></i>';
          });
          media.appendChild(image);
        } else {
          media.innerHTML = '<i class="fa-solid fa-box" aria-hidden="true"></i>';
        }
        const title = document.createElement("span");
        title.className = "autocomplete-option-title";
        title.textContent = option.value;
        item.append(media, title);
        item.addEventListener("mousedown", (event) => {
          event.preventDefault();
          choose(option);
        });
        menu.appendChild(item);
      });
      menu.hidden = false;
    }

    input.addEventListener("focus", render);
    input.addEventListener("input", render);
    input.addEventListener("keydown", (event) => {
      const items = Array.from(menu.querySelectorAll(".autocomplete-option"));
      if (event.key === "Escape") {
        close();
      } else if (event.key === "ArrowDown" && items.length) {
        event.preventDefault();
        activeIndex = (activeIndex + 1) % items.length;
      } else if (event.key === "ArrowUp" && items.length) {
        event.preventDefault();
        activeIndex = (activeIndex - 1 + items.length) % items.length;
      } else if (event.key === "Enter" && activeIndex >= 0 && items[activeIndex]) {
        event.preventDefault();
        choose(options.find((option) => option.value === items[activeIndex].querySelector(".autocomplete-option-title").textContent));
        return;
      }
      items.forEach((item, index) => item.classList.toggle("is-active", index === activeIndex));
    });
    document.addEventListener("click", (event) => {
      if (!wrapper.contains(event.target)) close();
    });
  }

  document.querySelectorAll("input[list]").forEach((input) => {
    const list = document.getElementById(input.getAttribute("list"));
    if (list) setupAutocomplete(input, list);
  });

  const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      mutation.addedNodes.forEach((node) => {
        if (node.nodeType !== Node.ELEMENT_NODE) return;
        const inputs = node.matches?.("input[list]") ? [node] : Array.from(node.querySelectorAll?.("input[list]") || []);
        inputs.forEach((input) => {
          const list = document.getElementById(input.getAttribute("list"));
          if (list) setupAutocomplete(input, list);
        });
      });
    });
  });
  observer.observe(document.body, { childList: true, subtree: true });

  const mappings = {
    quantity: "suggestedQuantity",
    unit: "suggestedUnit",
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
    const listId = input.dataset.autocompleteSource || input.getAttribute("list");
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
    const usePieceSuggestion = form.dataset.priorQuantityMode !== "measure";
    Object.entries(mappings).forEach(([fieldName, dataKey]) => {
      const resolvedKey = fieldName === "quantity" && !usePieceSuggestion ? "typicalQuantity" : dataKey;
      const resolvedUnit = fieldName === "unit" && !usePieceSuggestion ? "typicalUnit" : resolvedKey;
      setField(form, fieldName, option.dataset[resolvedUnit] || "");
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

  function setupLlmLoading(form) {
    if (!form.hasAttribute("data-prior-llm-loading")) {
      return;
    }

    const input = form.querySelector("[data-prior-name]");
    const idInput = form.querySelector("[data-prior-id]");
    const status = form.querySelector("[data-prior-llm-status]");
    const submitButton = form.querySelector("[data-prior-submit-button]");
    if (!input || !idInput) {
      return;
    }

    form.addEventListener("submit", () => {
      const hasName = input.value.trim().length > 0;
      const hasExistingPrior = idInput.value.trim().length > 0;
      if (!hasName || hasExistingPrior) {
        return;
      }

      if (status) {
        status.classList.remove("is-hidden");
      }
      if (submitButton) {
        submitButton.disabled = true;
      }
    });
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
    setupLlmLoading(form);
  });
})();
