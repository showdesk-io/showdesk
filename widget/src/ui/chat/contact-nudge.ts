/**
 * Contact Nudge — Gentle inline prompt for anonymous users to add their info.
 *
 * Shown once after the first message is sent.
 */

import type { WidgetStore } from "../../state/widget-state";

export function renderContactNudge(
  store: WidgetStore,
  onSave: (name: string, email: string) => void,
): HTMLElement {
  const card = document.createElement("div");
  card.className = "sd-contact-nudge";

  const msg = document.createElement("div");
  msg.className = "sd-nudge-text";
  msg.textContent = "Want to receive updates? Add your info.";

  const form = document.createElement("div");
  form.className = "sd-nudge-form";
  form.style.display = "none";

  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.placeholder = "Your name";
  nameInput.className = "sd-input";

  const emailInput = document.createElement("input");
  emailInput.type = "email";
  emailInput.placeholder = "you@example.com";
  emailInput.className = "sd-input";

  const saveBtn = document.createElement("button");
  saveBtn.className = "sd-btn-small sd-btn-primary";
  saveBtn.textContent = "Save";
  saveBtn.onclick = () => {
    const name = nameInput.value.trim();
    const email = emailInput.value.trim();
    if (email && email.includes("@")) {
      onSave(name, email);
      store.update({ contactNudgeDismissed: true });
      card.remove();
    } else {
      emailInput.style.borderColor = "#ef4444";
    }
  };

  form.appendChild(nameInput);
  form.appendChild(emailInput);
  form.appendChild(saveBtn);

  const actions = document.createElement("div");
  actions.className = "sd-nudge-actions";

  const expandBtn = document.createElement("button");
  expandBtn.className = "sd-btn-small sd-btn-secondary";
  expandBtn.textContent = "Add info";
  expandBtn.onclick = () => {
    form.style.display = "flex";
    actions.style.display = "none";
    nameInput.focus();
  };

  const dismissBtn = document.createElement("button");
  dismissBtn.className = "sd-btn-small sd-btn-link";
  dismissBtn.textContent = "Not now";
  dismissBtn.onclick = () => {
    store.update({ contactNudgeDismissed: true });
    card.remove();
  };

  actions.appendChild(expandBtn);
  actions.appendChild(dismissBtn);

  card.appendChild(msg);
  card.appendChild(actions);
  card.appendChild(form);

  return card;
}
