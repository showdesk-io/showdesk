/**
 * Floating action button for opening the widget.
 *
 * Also displays an unread badge when there are agent replies.
 * During screen recording, transforms into a mini controller
 * with stop button, audio toggle, and elapsed timer.
 */

import type { ShowdeskConfig } from "../types";

let buttonEl: HTMLButtonElement | null = null;
let badgeEl: HTMLElement | null = null;
let normalContent: string = "";
let timerInterval: ReturnType<typeof setInterval> | null = null;

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
  normalContent = button.innerHTML;

  button.addEventListener("click", () => onClick());

  buttonEl = button;
  container.appendChild(button);
}

/**
 * Transform the FAB into a recording controller.
 * Shows: [recording dot + timer] [mic toggle] [stop button]
 */
export function showRecordingController(callbacks: {
  onStop: () => void;
  onToggleAudio: () => boolean;
  audioEnabled: boolean;
}): void {
  if (!buttonEl) return;

  // Remove normal click handler by replacing the element's event listeners
  const newButton = buttonEl.cloneNode(false) as HTMLButtonElement;
  buttonEl.replaceWith(newButton);
  buttonEl = newButton;

  let audioOn = callbacks.audioEnabled;
  let elapsed = 0;

  buttonEl.className = buttonEl.className.replace("sd-button", "sd-button sd-button-recording");
  buttonEl.innerHTML = `
    <span class="sd-rec-dot"></span>
    <span class="sd-rec-timer">0:00</span>
    <button class="sd-rec-mic" title="Toggle microphone" aria-label="Toggle microphone">
      ${audioOn ? "🎤" : "🔇"}
    </button>
    <button class="sd-rec-stop" title="Stop recording" aria-label="Stop recording">
      ⏹
    </button>
  `;

  // Prevent FAB click from doing anything
  buttonEl.onclick = (e) => e.preventDefault();

  const timerEl = buttonEl.querySelector(".sd-rec-timer") as HTMLElement;
  const micBtn = buttonEl.querySelector(".sd-rec-mic") as HTMLElement;
  const stopBtn = buttonEl.querySelector(".sd-rec-stop") as HTMLElement;

  // Timer
  timerInterval = setInterval(() => {
    elapsed++;
    const min = Math.floor(elapsed / 60);
    const sec = elapsed % 60;
    timerEl.textContent = `${min}:${sec.toString().padStart(2, "0")}`;
  }, 1000);

  // Mic toggle
  micBtn.onclick = (e) => {
    e.stopPropagation();
    audioOn = callbacks.onToggleAudio();
    micBtn.textContent = audioOn ? "🎤" : "🔇";
    micBtn.title = audioOn ? "Mute microphone" : "Unmute microphone";
  };

  // Stop
  stopBtn.onclick = (e) => {
    e.stopPropagation();
    callbacks.onStop();
  };
}

/**
 * Restore the FAB to its normal state after recording ends.
 */
export function hideRecordingController(onClick: () => void): void {
  if (timerInterval) {
    clearInterval(timerInterval);
    timerInterval = null;
  }
  if (!buttonEl) return;

  const newButton = buttonEl.cloneNode(false) as HTMLButtonElement;
  buttonEl.replaceWith(newButton);
  buttonEl = newButton;

  buttonEl.className = buttonEl.className.replace(" sd-button-recording", "");
  buttonEl.innerHTML = normalContent;
  buttonEl.addEventListener("click", () => onClick());
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
