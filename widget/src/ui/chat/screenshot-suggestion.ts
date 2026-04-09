/**
 * Screenshot Suggestion — Card shown when auto-screenshot is available.
 *
 * "We captured your screen. Add it to the conversation?"
 * [Add] [Dismiss]
 */

import type { WidgetStore } from "../../state/widget-state";

export function renderScreenshotSuggestion(
  store: WidgetStore,
  onAdd: (blob: Blob) => void,
): HTMLElement {
  const card = document.createElement("div");
  card.className = "sd-screenshot-suggestion";

  const preview = document.createElement("div");
  preview.className = "sd-screenshot-preview";
  if (store.state.screenshotSuggestionUrl) {
    const img = document.createElement("img");
    img.src = store.state.screenshotSuggestionUrl;
    img.alt = "Screenshot";
    preview.appendChild(img);
  }

  const text = document.createElement("div");
  text.className = "sd-screenshot-text";
  text.textContent = "We captured your screen. Add it?";

  const actions = document.createElement("div");
  actions.className = "sd-screenshot-actions";

  const addBtn = document.createElement("button");
  addBtn.className = "sd-btn-small sd-btn-primary";
  addBtn.textContent = "Add";
  addBtn.onclick = () => {
    const blob = store.state.screenshotSuggestion;
    if (blob) onAdd(blob);
    dismiss();
  };

  const dismissBtn = document.createElement("button");
  dismissBtn.className = "sd-btn-small sd-btn-secondary";
  dismissBtn.textContent = "Dismiss";
  dismissBtn.onclick = dismiss;

  actions.appendChild(addBtn);
  actions.appendChild(dismissBtn);

  card.appendChild(preview);
  card.appendChild(text);
  card.appendChild(actions);

  function dismiss(): void {
    if (store.state.screenshotSuggestionUrl) {
      URL.revokeObjectURL(store.state.screenshotSuggestionUrl);
    }
    store.update({
      screenshotSuggestion: null,
      screenshotSuggestionUrl: null,
    });
    card.remove();
  }

  return card;
}
