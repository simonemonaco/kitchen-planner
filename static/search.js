(() => {
  window.normalizeSearchText = (value) => (value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase();
})();
