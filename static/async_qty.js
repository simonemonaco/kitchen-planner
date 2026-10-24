(() => {
  // Intercepts any form marked [data-qty-form] inside a [data-async-qty] wrapper.
  // Sends the POST via fetch, updates the nearest [data-qty-pill] with the new
  // formatted quantity returned by the server, without a page reload.
  // Falls back to normal form submission on network/parse errors.

  function attachForm(form) {
    const wrapper = form.closest("[data-async-qty]");
    if (!wrapper) return;

    form.addEventListener("submit", async (e) => {
      e.preventDefault();

      const pill = wrapper.querySelector("[data-qty-pill]");
      const oldQuantity = Number(pill?.dataset.itemQuantity);

      const btn = form.querySelector("button[type='submit']");
      if (btn) btn.disabled = true;

      try {
        const resp = await fetch(form.action, {
          method: "POST",
          headers: { "X-Requested-With": "XMLHttpRequest" },
          body: new FormData(form),
        });

        if (!resp.ok) return;

        const data = await resp.json();
        if (data.ok) {
          if (pill) {
            pill.textContent = data.qty_display;
            if (data.quantity != null) pill.dataset.itemQuantity = data.quantity;
            if (data.unit) pill.dataset.itemUnit = data.unit;
          }
          const card = wrapper.closest("article");
          if (card) card.classList.toggle("is-zero", Number(data.quantity) <= 0);
          const previousQuantity = data.previous_quantity == null
            ? oldQuantity
            : Number(data.previous_quantity);
          const change = wrapper.closest(".item-main")?.querySelector("[data-today-quantity-change]");
          if (change) {
            const amount = Number(data.today_quantity_change || 0);
            change.hidden = !amount;
            change.classList.toggle("is-added", amount > 0);
            change.classList.toggle("is-used", amount < 0);
            change.innerHTML = `<span aria-hidden="true">${amount > 0 ? "▲" : "▼"}</span> ${data.today_quantity_change_display || Math.abs(amount)}`;
          }
          if (wrapper.hasAttribute("data-inventory-zero-confirm") && previousQuantity > 0 && Number(data.quantity) <= 0) {
            if (card) card.dataset.restoreQuantity = previousQuantity;
            window.promptInventoryZero?.(card);
          }
        }
      } catch (_) {
        // Network error — let the native submit handle it
        form.submit();
      } finally {
        if (btn) btn.disabled = false;
      }
    });
  }

  document.querySelectorAll("[data-async-qty] [data-qty-form]").forEach(attachForm);

  const zeroDialog = document.querySelector("[data-quantity-zero-dialog]");
  if (zeroDialog) {
    const itemName = zeroDialog.querySelector("[data-zero-item-name]");
    const finishButton = zeroDialog.querySelector("[data-zero-confirm]");
    const cancelButton = zeroDialog.querySelector("[data-zero-cancel]");
    let pendingCard = null;

    window.promptInventoryZero = (card) => {
      pendingCard = card;
      itemName.textContent = card?.querySelector("h3")?.textContent?.trim() || "Questo prodotto";
      zeroDialog.showModal();
    };

    cancelButton?.addEventListener("click", () => {
      pendingCard = null;
      zeroDialog.close();
    });
    finishButton?.addEventListener("click", () => {
      const form = pendingCard?.querySelector("[data-finish-inventory-form]");
      if (form && pendingCard?.dataset.restoreQuantity) {
        let input = form.querySelector("[name='restore_quantity']");
        if (!input) {
          input = document.createElement("input");
          input.type = "hidden";
          input.name = "restore_quantity";
          form.appendChild(input);
        }
        input.value = pendingCard.dataset.restoreQuantity;
      }
      pendingCard = null;
      zeroDialog.close();
      form?.requestSubmit();
    });
    zeroDialog.addEventListener("click", (event) => {
      if (event.target === zeroDialog) {
        pendingCard = null;
        zeroDialog.close();
      }
    });
  }
})();
