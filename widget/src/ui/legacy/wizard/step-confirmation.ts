/**
 * Confirmation step: success screen with ticket reference.
 *
 * Shows a checkmark, the ticket reference number, a thank-you message,
 * and a close button.
 */

export function renderConfirmationStep(
  container: HTMLElement,
  ticketReference: string,
  onClose: () => void,
): void {
  container.innerHTML = "";

  const wrapper = document.createElement("div");
  wrapper.className = "sd-wizard-step sd-success";

  // Checkmark icon
  const checkmark = document.createElement("div");
  checkmark.className = "sd-confirmation-checkmark";
  checkmark.innerHTML = `
    <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
      <circle cx="32" cy="32" r="30" stroke="#22c55e" stroke-width="3" fill="#f0fdf4"/>
      <path d="M20 33 L28 41 L44 25" stroke="#22c55e" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
    </svg>
  `;
  wrapper.appendChild(checkmark);

  // Title
  const title = document.createElement("h3");
  title.textContent = "Message sent!";
  wrapper.appendChild(title);

  // Ticket reference
  const refText = document.createElement("p");
  refText.textContent = `Reference: ${ticketReference}`;
  wrapper.appendChild(refText);

  // Subtitle
  const subtitle = document.createElement("p");
  subtitle.style.color = "var(--sd-text-light)";
  subtitle.textContent = "We'll get back to you as soon as possible.";
  wrapper.appendChild(subtitle);

  // Close button
  const closeBtn = document.createElement("button");
  closeBtn.className = "sd-submit-btn";
  closeBtn.style.marginTop = "16px";
  closeBtn.textContent = "Close";
  closeBtn.addEventListener("click", onClose);
  wrapper.appendChild(closeBtn);

  container.appendChild(wrapper);
}
