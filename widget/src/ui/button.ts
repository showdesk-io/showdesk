/**
 * Floating action button for opening the widget.
 *
 * Zero friction: always visible, instantly recognizable,
 * one click to get help.
 */

import type { ShowdeskConfig } from "../types";

export function createButton(config: ShowdeskConfig, onClick: () => void): void {
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
  button.addEventListener("click", onClick);

  container.appendChild(button);
}
