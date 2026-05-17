(() => {
  const form = document.querySelector("[data-receipt-upload]");
  if (!form) {
    return;
  }

  const imageInput = form.querySelector("[data-receipt-image]");
  const textArea = form.querySelector("[data-receipt-text]");
  const submitButton = form.querySelector("[data-receipt-submit]");
  const status = form.querySelector("[data-receipt-ocr-status]");
  const progress = form.querySelector("[data-receipt-ocr-progress]");
  let tesseractModulePromise = null;

  function updateStatus(message, isVisible, isBusy) {
    if (progress && message) {
      progress.textContent = message;
    }
    if (status) {
      status.classList.toggle("is-hidden", !isVisible);
      status.setAttribute("aria-busy", isBusy ? "true" : "false");
    }
  }

  function setSubmitting(isSubmitting) {
    if (submitButton) {
      submitButton.disabled = isSubmitting;
      submitButton.textContent = isSubmitting ? "Lettura in corso..." : "Leggi scontrino";
    }
  }

  async function loadTesseract() {
    if (window.Tesseract && typeof window.Tesseract.createWorker === "function") {
      return window.Tesseract;
    }

    if (!tesseractModulePromise) {
      tesseractModulePromise = import("https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.esm.min.js")
        .then((module) => module.default || module);
    }

    return tesseractModulePromise;
  }

  form.addEventListener("submit", async (event) => {
    const currentText = textArea ? textArea.value.trim() : "";
    const imageFile = imageInput && imageInput.files ? imageInput.files[0] : null;

    if (currentText || !imageFile) {
      return;
    }

    event.preventDefault();

    try {
      setSubmitting(true);
      updateStatus("Preparazione OCR", true, true);

      const { createWorker } = await loadTesseract();
      const worker = await createWorker("ita", 1, {
        logger: (message) => {
          if (!progress || !message || typeof message.progress !== "number") {
            return;
          }
          const percent = Math.max(0, Math.min(100, Math.round(message.progress * 100)));
          progress.textContent = `${message.status || "Elaborazione"} ${percent}%`;
        },
      });

      const result = await worker.recognize(imageFile);
      await worker.terminate();

      if (textArea) {
        textArea.value = (result && result.data && result.data.text) || "";
      }

      form.requestSubmit();
    } catch (_error) {
      setSubmitting(false);
      updateStatus("Non sono riuscito a caricare OCR nel browser. Inserisci il testo manualmente.", true, false);
    }
  });
})();
