/**
 * Floating action button for opening the widget.
 *
 * On click:
 *   1. Attempts to capture a screenshot (best-effort, non-blocking).
 *   2. Opens the messaging panel with the screenshot as a suggestion.
 *
 * Also displays an unread badge when there are agent replies.
 */

import type { ShowdeskConfig } from "../types";

let buttonEl: HTMLButtonElement | null = null;
let badgeEl: HTMLElement | null = null;

export function createButton(
  config: ShowdeskConfig,
  onClick: (screenshotBlob: Blob | null) => void,
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

  button.addEventListener("click", async () => {
    let screenshot: Blob | null = null;
    try {
      screenshot = await captureScreenshot();
    } catch {
      // Permission denied or API unavailable — continue without screenshot
    }
    onClick(screenshot);
  });

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

/**
 * Attempt to capture a screenshot of the current tab.
 * Uses getDisplayMedia with preferCurrentTab for a frictionless experience.
 * Returns null if the user declines or the API is unavailable.
 */
async function captureScreenshot(): Promise<Blob | null> {
  if (!navigator.mediaDevices?.getDisplayMedia) return null;

  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({
      video: true,
      // @ts-expect-error preferCurrentTab is Chrome-only
      preferCurrentTab: true,
    });
  } catch {
    return null;
  }

  const track = stream.getVideoTracks()[0];
  if (!track) return null;
  try {
    // @ts-expect-error ImageCapture not in all TS defs
    const imageCapture = new ImageCapture(track);
    const bitmap = await imageCapture.grabFrame();
    track.stop();

    const canvas = document.createElement("canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const ctx = canvas.getContext("2d")!;
    ctx.drawImage(bitmap, 0, 0);

    return new Promise<Blob | null>((resolve) =>
      canvas.toBlob((b) => resolve(b), "image/png"),
    );
  } catch {
    track.stop();
    return null;
  }
}
