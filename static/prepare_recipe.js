(() => {
  const dialog = document.querySelector('[data-prepare-dialog]');
  if (!dialog) return;
  const form = dialog.querySelector('[data-prepare-form]');
  const valueInput = dialog.querySelector('[data-prepare-value]');
  const modeToggle = dialog.querySelector('input[type="checkbox"][data-prepare-mode]');
  const modeValue = dialog.querySelector('[data-prepare-mode-value]');
  const modeText = dialog.querySelector('.prepare-toggle-text');
  const peopleLabel = dialog.querySelector('[data-prepare-people-label]');
  const total = dialog.querySelector('[data-prepare-total]');
  const ingredients = dialog.querySelector('[data-prepare-ingredients]');
  const error = dialog.querySelector('[data-prepare-error]');
  let recipeId = null;
  let recipeName = '';
  let previewUrl = '';
  let lastPreview = null;

  const format = (number) => Number(number).toLocaleString('it-IT', { maximumFractionDigits: 2 });
  const selectedMode = () => modeToggle?.checked ? 'quantity' : 'people';

  function updateModeUI() {
    const quantityMode = selectedMode() === 'quantity';
    modeValue.value = selectedMode();
    modeText?.classList.toggle('is-quantity', quantityMode);
    modeToggle?.setAttribute('aria-label', quantityMode ? 'Passa a numero di persone' : 'Passa a quantità totale');
    peopleLabel.firstChild.textContent = quantityMode ? 'Quantità totale (g)' : 'Persone';
    valueInput.step = quantityMode ? 'any' : '1';
    valueInput.min = quantityMode ? '0.01' : '1';
  }

  function render(data) {
    lastPreview = data;
    error.hidden = true;
    total.textContent = data.total > 0 ? `Totale pesato: ${format(data.total)} g` : 'Totale pesato non determinabile (ingredienti in pezzi senza equivalente).';
    ingredients.innerHTML = data.ingredients.map(item => `
      <div class="prepare-ingredient ${item.status === 'shortage' ? 'is-shortage' : ''}">
        <span>${item.name}</span>
        <strong>${format(item.required)} ${item.unit}</strong>
        <small>${item.status === 'shortage' ? `Disponibili ${format(item.available)} ${item.unit} · da comprare ${format(item.missing)} ${item.unit}` : `Disponibili ${format(item.available)} ${item.unit}`}</small>
      </div>`).join('');
  }

  async function update() {
    const value = Number(valueInput.value);
    if (!value || value <= 0) return;
    const url = new URL(previewUrl, window.location.href);
    url.searchParams.set('mode', selectedMode());
    url.searchParams.set('value', value);
    try {
      const response = await fetch(url);
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || 'Calcolo non riuscito.');
      render(data);
    } catch (exception) {
      error.textContent = exception.message;
      error.hidden = false;
    }
  }

  document.querySelectorAll('[data-open-prepare-recipe]').forEach(button => {
    button.addEventListener('click', () => {
      recipeId = button.dataset.recipeId;
      recipeName = button.dataset.recipeName;
      previewUrl = button.dataset.previewUrl;
      form.action = button.dataset.submitUrl;
      dialog.querySelector('[data-prepare-title]').textContent = button.dataset.label || `Prepara ${recipeName}`;
      dialog.querySelector('[data-prepare-people-label]').firstChild.textContent = 'Persone';
      valueInput.value = button.dataset.defaultPeople || 2;
      modeToggle.checked = false;
      updateModeUI();
      dialog.showModal();
      update();
      valueInput.focus();
      valueInput.select();
    });
  });
  modeToggle?.addEventListener('change', () => {
    const quantityMode = selectedMode() === 'quantity';
    if (quantityMode && lastPreview?.total > 0) valueInput.value = lastPreview.total;
    updateModeUI();
    update();
  });
  valueInput.addEventListener('input', update);
  dialog.querySelector('[data-prepare-cancel]')?.addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
})();
