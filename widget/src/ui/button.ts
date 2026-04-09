/**
 * Floating action button for opening the widget.
 *
 * Also displays an unread badge when there are agent replies.
 */

import type { ShowdeskConfig } from "../types";

let buttonEl: HTMLButtonElement | null = null;
let badgeEl: HTMLElement | null = null;

export function createButton(
  config: ShowdeskConfig,
  onClick: () => void,
): void {
  let container = document.getElementById("showdesk-widget-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "showdesk-widget-container";
    document.body.appendChild(container);
  }

  const button = document.createElement("button");
  button.className = `sd-button ${config.position}`;
  button.setAttribute("aria-label", "Open support widget");
  button.innerHTML = `
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
    </svg>
    ${config.label}
  `;

  button.addEventListener("click", () => onClick());

  buttonEl = button;
  container.appendChild(button);
}

/**
 * Update the unread badge count on the FAB.
 */
export function updateBadge(count: number): void {
  if (!buttonEl) return;

  if (count <= 0) {
    if (badgeEl) {
      badgeEl.remove();
      badgeEl = null;
    }
    return;
  }

  if (!badgeEl) {
    badgeEl = document.createElement("span");
    badgeEl.className = "sd-fab-badge";
    buttonEl.appendChild(badgeEl);
  }
  badgeEl.textContent = count > 9 ? "9+" : String(count);
}

/**
 * Show/hide the FAB button.
 */
export function setButtonVisible(visible: boolean): void {
  if (buttonEl) {
    buttonEl.style.display = visible ? "" : "none";
  }
}

