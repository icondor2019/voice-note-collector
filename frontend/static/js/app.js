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
    const hasHiddenSelection = moreToggle.dataset.hasHiddenSelection === "true";
    setMoreLabelsOpen(hasHiddenSelection);
    moreToggle.addEventListener("click", () => setMoreLabelsOpen(moreRegion.hidden));
  }
});
