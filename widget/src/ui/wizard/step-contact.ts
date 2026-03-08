/**
 * Contact / recap step: identity-aware form or summary.
 *
 * Two modes:
 * - Identity known (hasIdentity=true): shows a recap card with user info,
 *   issue type badge, description preview, capture info, and Edit + Send buttons.
 * - Anonymous (hasIdentity=false): shows name + email fields + Send button.
 */

import type { WizardState } from "./wizard-state";

export function renderContactStep(
  container: HTMLElement,
  state: WizardState,
  hasIdentity: boolean,
  onSubmit: (updates: Partial<WizardState>) => void,
  onBack: () => void,
): void {
  container.innerHTML = "";

  const wrapper = document.createElement("div");
  wrapper.className = "sd-wizard-step";

  if (hasIdentity) {
    renderRecap(wrapper, state, onSubmit, onBack);
  } else {
    renderContactForm(wrapper, state, onSubmit, onBack);
  }

  container.appendChild(wrapper);
}

function renderRecap(
  wrapper: HTMLElement,
  state: WizardState,
  onSubmit: (updates: Partial<WizardState>) => void,
  onBack: () => void,
): void {
  const title = document.createElement("h3");
  title.className = "sd-wizard-title";
  title.textContent = "Ready to send?";
  wrapper.appendChild(title);

  const card = document.createElement("div");
  card.className = "sd-recap-card";

  // User info
  const userRow = document.createElement("div");
  userRow.className = "sd-recap-row";
  userRow.innerHTML = `<strong>${escapeHtml(state.requesterName)}</strong> &lt;${escapeHtml(state.requesterEmail)}&gt;`;
  card.appendChild(userRow);

  // Issue type badge
  if (state.issueType) {
    const badge = document.createElement("span");
    badge.className = "sd-issue-badge";
    badge.textContent = state.issueType;
    card.appendChild(badge);
  }

  // Description preview
  const descPreview = document.createElement("p");
  descPreview.className = "sd-recap-description";
  const truncated = state.description.length > 120
    ? state.description.slice(0, 120) + "..."
    : state.description;
  descPreview.textContent = truncated;
  card.appendChild(descPreview);

  // Capture info
  if (state.recordedBlob) {
    const captureInfo = document.createElement("div");
    captureInfo.className = "sd-recap-row";
    const sizeMB = (state.recordedBlob.size / (1024 * 1024)).toFixed(1);
    captureInfo.textContent = `Video attached (${sizeMB} MB)`;
    card.appendChild(captureInfo);
  }

  // Technical context mention
  const contextInfo = document.createElement("div");
  contextInfo.className = "sd-recap-row sd-recap-context";
  contextInfo.textContent = "Console errors and technical context will be included automatically.";
  card.appendChild(contextInfo);

  wrapper.appendChild(card);

  // Actions
  const actionsDiv = document.createElement("div");
  actionsDiv.className = "sd-wizard-actions";

  const editBtn = document.createElement("button");
  editBtn.className = "sd-back-btn";
  editBtn.textContent = "\u25C0 Edit";
  editBtn.addEventListener("click", onBack);

  const sendBtn = document.createElement("button");
  sendBtn.className = "sd-submit-btn";
  sendBtn.textContent = "Send";
  sendBtn.addEventListener("click", () => {
    onSubmit({});
  });

  actionsDiv.appendChild(editBtn);
  actionsDiv.appendChild(sendBtn);
  wrapper.appendChild(actionsDiv);
}

function renderContactForm(
  wrapper: HTMLElement,
  state: WizardState,
  onSubmit: (updates: Partial<WizardState>) => void,
  onBack: () => void,
): void {
  const title = document.createElement("h3");
  title.className = "sd-wizard-title";
  title.textContent = "Your contact details";
  wrapper.appendChild(title);

  // Name field
  const nameField = document.createElement("div");
  nameField.className = "sd-field";

  const nameLabel = document.createElement("label");
  nameLabel.textContent = "Name";
  nameField.appendChild(nameLabel);

  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.placeholder = "Your name";
  nameInput.value = state.requesterName;
  nameField.appendChild(nameInput);
  wrapper.appendChild(nameField);

  // Email field
  const emailField = document.createElement("div");
  emailField.className = "sd-field";

  const emailLabel = document.createElement("label");
  emailLabel.textContent = "Email";
  emailField.appendChild(emailLabel);

  const emailInput = document.createElement("input");
  emailInput.type = "email";
  emailInput.placeholder = "you@example.com";
  emailInput.value = state.requesterEmail;
  emailField.appendChild(emailInput);
  wrapper.appendChild(emailField);

  // Actions
  const actionsDiv = document.createElement("div");
  actionsDiv.className = "sd-wizard-actions";

  const backBtn = document.createElement("button");
  backBtn.className = "sd-back-btn";
  backBtn.textContent = "\u25C0 Back";
  backBtn.addEventListener("click", onBack);

  const sendBtn = document.createElement("button");
  sendBtn.className = "sd-submit-btn";
  sendBtn.textContent = "Send";
  sendBtn.addEventListener("click", () => {
    const name = nameInput.value.trim();
    const email = emailInput.value.trim();

    // Basic validation
    if (!name || !email || !email.includes("@")) {
      highlightInvalid(nameInput, !name);
      highlightInvalid(emailInput, !email || !email.includes("@"));
      return;
    }

    onSubmit({
      requesterName: name,
      requesterEmail: email,
    });
  });

  actionsDiv.appendChild(backBtn);
  actionsDiv.appendChild(sendBtn);
  wrapper.appendChild(actionsDiv);
}

function highlightInvalid(input: HTMLInputElement, invalid: boolean): void {
  input.style.borderColor = invalid ? "#ef4444" : "";
}

function escapeHtml(text: string): string {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}
