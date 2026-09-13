document.addEventListener("htmx:responseError", () => {
  const region = document.querySelector("[aria-live='polite']");
  if (region) region.setAttribute("data-error", "The library could not load more items.");
});

document.querySelectorAll("[data-library-filters]").forEach((form) => {
  const moreToggle = form.querySelector("[data-more-labels-toggle]");
  const moreRegion = form.querySelector("[data-more-labels-region]");
  const setMoreLabelsOpen = (open) => {
    if (!moreToggle || !moreRegion) return;
    moreRegion.hidden = !open;
    moreToggle.setAttribute("aria-expanded", String(open));
    moreToggle.innerHTML = open
      ? 'Show less labels <span aria-hidden="true">↑</span>'
      : 'See more labels <span aria-hidden="true">↓</span>';
  };
  if (moreToggle && moreRegion) {
    setMoreLabelsOpen(moreToggle.dataset.hasHiddenSelection === "true");
    moreToggle.addEventListener("click", () => setMoreLabelsOpen(moreRegion.hidden));
  }
});

const selectionRoot = document.querySelector("[data-note-selection]");

if (selectionRoot) {
  const toolbar = selectionRoot.querySelector("#selection-toolbar");
  const count = selectionRoot.querySelector("[data-selection-count]");
  const source = selectionRoot.querySelector("[data-selection-source]");
  const status = selectionRoot.querySelector("[data-selection-status]");
  const cancelSelection = selectionRoot.querySelector("[data-cancel-selection]");
  const openBuild = selectionRoot.querySelector("[data-open-build]");
  const dialog = selectionRoot.querySelector("#build-dialog");
  const summary = selectionRoot.querySelector("[data-build-summary]");
  const error = selectionRoot.querySelector("[data-build-error]");
  const confirmBuild = selectionRoot.querySelector("[data-confirm-build]");
  const selected = new Map();
  let selectionMode = false;
  let activeSourceId = "";
  let longPressTimer = null;
  let pointerStart = null;
  let longPressTriggered = false;
  let building = false;

  const cards = () => Array.from(document.querySelectorAll("[data-note-card]"));
  const cardFor = (target) => target.closest("[data-note-card]");
  const isEligible = (card) => card && card.dataset.selectable === "true";

  const syncCard = (card) => {
    const id = card.dataset.noteId;
    const otherSource = Boolean(activeSourceId && card.dataset.sourceId && card.dataset.sourceId !== activeSourceId);
    const disabled = !isEligible(card) || (selectionMode && otherSource && !selected.has(id));
    const checkbox = card.querySelector("[data-note-checkbox]");
    card.classList.toggle("is-selected", selected.has(id));
    card.classList.toggle("is-selection-disabled", selectionMode && disabled);
    card.setAttribute("aria-disabled", String(disabled));
    if (checkbox) {
      checkbox.checked = selected.has(id);
      checkbox.disabled = disabled;
    }
  };

  const syncSelection = () => {
    cards().forEach(syncCard);
    count.textContent = String(selected.size);
    const selectedSourceName = selected.size ? Array.from(selected.values())[0].sourceName : "";
    source.textContent = selectedSourceName ? `· ${selectedSourceName}` : "";
    openBuild.disabled = selected.size === 0 || building;
    toolbar.hidden = !selectionMode;
    document.body.classList.toggle("note-selection-active", selectionMode);
  };

  const leaveSelection = () => {
    selected.clear();
    selectionMode = false;
    activeSourceId = "";
    status.textContent = "Select notes to build a document.";
    syncSelection();
  };

  const toggleCard = (card) => {
    if (!isEligible(card) || building) return;
    const id = card.dataset.noteId;
    const cardSourceId = card.dataset.sourceId || "";
    if (activeSourceId && cardSourceId && cardSourceId !== activeSourceId && !selected.has(id)) return;
    if (selected.has(id)) {
      selected.delete(id);
      if (selected.size === 0) activeSourceId = "";
    } else {
      if (!activeSourceId) activeSourceId = cardSourceId;
      selected.set(id, {sourceId: cardSourceId, sourceName: card.dataset.sourceName || "Unknown source"});
    }
    syncSelection();
  };

  const enterSelection = (card) => {
    if (!isEligible(card) || building) return;
    selectionMode = true;
    if (!activeSourceId) activeSourceId = card.dataset.sourceId || "";
    syncSelection();
  };

  const clearLongPress = () => {
    if (longPressTimer !== null) window.clearTimeout(longPressTimer);
    longPressTimer = null;
    pointerStart = null;
  };

  selectionRoot.addEventListener("pointerdown", (event) => {
    const card = cardFor(event.target);
    if (!card || !isEligible(card) || event.target.closest("button, input, label")) return;
    clearLongPress();
    pointerStart = {x: event.clientX, y: event.clientY};
    longPressTimer = window.setTimeout(() => {
      longPressTriggered = true;
      enterSelection(card);
      toggleCard(card);
    }, 500);
  });

  selectionRoot.addEventListener("pointermove", (event) => {
    if (!pointerStart) return;
    if (Math.abs(event.clientX - pointerStart.x) > 10 || Math.abs(event.clientY - pointerStart.y) > 10) clearLongPress();
  });
  selectionRoot.addEventListener("pointerup", clearLongPress);
  selectionRoot.addEventListener("pointercancel", clearLongPress);
  window.addEventListener("scroll", clearLongPress, {passive: true});
  selectionRoot.addEventListener("contextmenu", (event) => {
    if (selectionMode) event.preventDefault();
  });

  selectionRoot.addEventListener("click", (event) => {
    const selectButton = event.target.closest("[data-select-note]");
    if (selectButton) {
      event.preventDefault();
      event.stopPropagation();
      const card = cardFor(selectButton);
      if (!selectionMode) enterSelection(card);
      toggleCard(card);
      return;
    }
    const card = cardFor(event.target);
    if (!card || !selectionMode) return;
    if (longPressTriggered) {
      longPressTriggered = false;
      event.preventDefault();
      return;
    }
    if (event.target.closest("a")) {
      event.preventDefault();
      toggleCard(card);
    } else if (!event.target.closest("button, input, label")) {
      toggleCard(card);
    }
  });

  selectionRoot.addEventListener("change", (event) => {
    const checkbox = event.target.closest("[data-note-checkbox]");
    if (checkbox) toggleCard(cardFor(checkbox));
  });

  cancelSelection.addEventListener("click", leaveSelection);
  openBuild.addEventListener("click", () => {
    if (!selected.size || building) return;
    const first = Array.from(selected.values())[0];
    summary.textContent = `Build one document from ${selected.size} selected note${selected.size === 1 ? "" : "s"} in ${first.sourceName}.`;
    error.hidden = true;
    dialog.showModal();
  });

  confirmBuild.addEventListener("click", async () => {
    if (!selected.size || building) return;
    building = true;
    dialog.classList.add("is-building");
    confirmBuild.textContent = "Building document…";
    error.hidden = true;
    status.textContent = "Building document…";
    syncSelection();
    const values = Array.from(selected.entries());
    const first = values[0][1];
    try {
      const response = await fetch(selectionRoot.dataset.buildEndpoint, {
        method: "POST",
        headers: {"Content-Type": "application/json", "X-CSRF-Token": selectionRoot.dataset.csrfToken || ""},
        body: JSON.stringify({source_id: first.sourceId, note_ids: values.map(([id]) => id)}),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "The document could not be built. Please try again.");
      window.location.assign(body.redirect_url);
    } catch (buildError) {
      error.textContent = buildError.message || "The document could not be built. Please try again.";
      error.hidden = false;
      status.textContent = "Build failed. Your selection is still available to retry.";
      building = false;
      dialog.classList.remove("is-building");
      confirmBuild.textContent = "Build document";
      syncSelection();
    }
  });

  dialog.addEventListener("close", () => {
    if (!building) {
      error.hidden = true;
      status.textContent = "Select notes to build a document.";
    }
  });
  document.body.addEventListener("htmx:afterSwap", syncSelection);
  syncSelection();
}
