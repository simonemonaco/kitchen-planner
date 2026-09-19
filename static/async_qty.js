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
          const pill = wrapper.querySelector("[data-qty-pill]");
          if (pill) pill.textContent = data.qty_display;
          const change = wrapper.closest(".item-main")?.querySelector("[data-today-quantity-change]");
          if (change) {
            const amount = Number(data.today_quantity_change || 0);
            change.hidden = !amount;
            change.classList.toggle("is-added", amount > 0);
            change.classList.toggle("is-used", amount < 0);
            change.innerHTML = `<span aria-hidden="true">${amount > 0 ? "▲" : "▼"}</span> ${data.today_quantity_change_display || Math.abs(amount)}`;
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
})();
