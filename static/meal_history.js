(() => {
  const dialog = document.querySelector("[data-meal-undo-dialog]");
  const form = document.querySelector("[data-meal-undo-form]");
  if (!dialog || !form) return;
  const description = dialog.querySelector("[data-meal-undo-description]");
  const date = dialog.querySelector("[data-meal-undo-date]");
  document.querySelectorAll("[data-undo-meal]").forEach((button) => {
    button.addEventListener("click", () => {
      form.action = `/meals/${button.dataset.mealId}/undo`;
      description.textContent = `Il consumo di “${button.dataset.mealName}” verrà annullato e le quantità torneranno nell’inventario.`;
      date.value = button.dataset.mealDate;
      dialog.showModal();
    });
  });
  dialog.querySelector("[data-meal-undo-cancel]").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
})();
