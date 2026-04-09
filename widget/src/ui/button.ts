/**
 * Floating action button for opening the widget.
 *
 * Also displays an unread badge when there are agent replies.
 * During screen recording, transforms into a mini controller
 * with stop button, audio toggle, mic selector, and elapsed timer.
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
 * Shows: [recording dot + timer] [mic toggle + selector] [stop button]
 */
export function showRecordingController(callbacks: {
  onStop: () => void;
  onToggleAudio: () => boolean;
  onSwitchMic: (deviceId: string) => Promise<void>;
  getCurrentMicId?: () => string;
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
    <span class="sd-rec-mic-wrapper">
      <span class="sd-rec-mic" title="${audioOn ? "Mute microphone" : "Unmute microphone"}" aria-label="Toggle microphone" role="button" tabindex="0">
        ${audioOn ? "🎤" : "🔇"}
      </span>
      <span class="sd-rec-mic-select" title="Choose microphone" aria-label="Choose microphone" role="button" tabindex="0">
        ▾
      </span>
    </span>
    <span class="sd-rec-stop" title="Stop recording" aria-label="Stop recording" role="button" tabindex="0">
      ⏹
    </span>
  `;

  // Prevent FAB click from doing anything
  buttonEl.onclick = (e) => e.preventDefault();

  const timerEl = buttonEl.querySelector(".sd-rec-timer") as HTMLElement;
  const micBtn = buttonEl.querySelector(".sd-rec-mic") as HTMLElement;
  const micSelectBtn = buttonEl.querySelector(".sd-rec-mic-select") as HTMLElement;
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

  // Mic selector
  micSelectBtn.onclick = (e) => {
    e.stopPropagation();
    showMicSelector(buttonEl!, callbacks.onSwitchMic, callbacks.getCurrentMicId?.());
  };

  // Stop
  stopBtn.onclick = (e) => {
    e.stopPropagation();
    callbacks.onStop();
  };
}

/**
 * Show a small dropdown with available microphone devices.
 */
async function showMicSelector(
  anchor: HTMLElement,
  onSelect: (deviceId: string) => Promise<void>,
  activeMicId?: string,
): Promise<void> {
  // Remove existing selector
  document.getElementById("sd-mic-selector")?.remove();

  let devices: MediaDeviceInfo[];
  try {
    devices = (await navigator.mediaDevices.enumerateDevices()).filter(
      (d) => d.kind === "audioinput" && d.deviceId,
    );
  } catch {
    return;
  }

  if (devices.length <= 1) return; // No alternative to show

  const menu = document.createElement("div");
  menu.id = "sd-mic-selector";
  menu.className = "sd-mic-selector";

  for (const device of devices) {
    const btn = document.createElement("button");
    const isActive = activeMicId ? device.deviceId === activeMicId : device.deviceId === "default";
    btn.className = `sd-mic-selector-item${isActive ? " sd-mic-selector-active" : ""}`;
    btn.textContent = device.label || `Microphone ${device.deviceId.slice(0, 8)}`;
    btn.onclick = async (e) => {
      e.stopPropagation();
      menu.remove();
      await onSelect(device.deviceId);
    };
    menu.appendChild(btn);
  }

  // Position above the FAB using fixed positioning
  const rect = anchor.getBoundingClientRect();
  menu.style.position = "fixed";
  menu.style.bottom = `${window.innerHeight - rect.top + 8}px`;
  menu.style.left = `${rect.left}px`;
  menu.style.width = `${rect.width}px`;

  // Add to widget container (not the FAB itself, to avoid position: relative)
  const widgetContainer = document.getElementById("showdesk-widget-container");
  (widgetContainer || document.body).appendChild(menu);

  // Close on outside click
  const closeHandler = (e: MouseEvent) => {
    if (!menu.contains(e.target as Node)) {
      menu.remove();
      document.removeEventListener("click", closeHandler);
    }
  };
  setTimeout(() => document.addEventListener("click", closeHandler), 0);
}

/**
 * Transform the FAB into a "waiting for popup" state.
 * Shows a pulsing dot and "Waiting..." text — no timer, no stop.
 * Transitions to recording controller when the popup starts recording.
 */
export function showPopupWaitingController(): void {
  if (!buttonEl) return;

  const newButton = buttonEl.cloneNode(false) as HTMLButtonElement;
  buttonEl.replaceWith(newButton);
  buttonEl = newButton;

  buttonEl.className = buttonEl.className.replace("sd-button", "sd-button sd-button-recording");
  buttonEl.innerHTML = `
    <span class="sd-rec-dot sd-rec-dot-waiting"></span>
    <span class="sd-rec-timer" style="color: #a0a0a0">Waiting…</span>
  `;

  buttonEl.onclick = (e) => e.preventDefault();
}

/**
 * Transform the FAB into a lightweight controller for popup-based recording.
 * Shows: [recording dot + timer] [stop button]
 * The actual recording runs in the popup — this is just a remote control.
 */
export function showPopupRecordingController(callbacks: {
  onStop: () => void;
  initialElapsed?: number;
}): void {
  if (!buttonEl) return;

  const newButton = buttonEl.cloneNode(false) as HTMLButtonElement;
  buttonEl.replaceWith(newButton);
  buttonEl = newButton;

  let elapsed = callbacks.initialElapsed ?? 0;

  buttonEl.className = buttonEl.className.replace("sd-button", "sd-button sd-button-recording");
  buttonEl.innerHTML = `
    <span class="sd-rec-dot"></span>
    <span class="sd-rec-timer">${formatElapsed(elapsed)}</span>
    <span class="sd-rec-stop" title="Stop recording" aria-label="Stop recording" role="button" tabindex="0">
      ⏹
    </span>
  `;

  buttonEl.onclick = (e) => e.preventDefault();

  const timerEl = buttonEl.querySelector(".sd-rec-timer") as HTMLElement;
  const stopBtn = buttonEl.querySelector(".sd-rec-stop") as HTMLElement;

  timerInterval = setInterval(() => {
    elapsed++;
    timerEl.textContent = formatElapsed(elapsed);
  }, 1000);

  stopBtn.onclick = (e) => {
    e.stopPropagation();
    callbacks.onStop();
  };
}

/**
 * Transform the FAB into an uploading indicator for popup recordings.
 * Shows: [spinner] [Uploading... X%]
 */
export function showPopupUploadingController(): void {
  if (!buttonEl) return;

  if (timerInterval) {
    clearInterval(timerInterval);
    timerInterval = null;
  }

  const newButton = buttonEl.cloneNode(false) as HTMLButtonElement;
  buttonEl.replaceWith(newButton);
  buttonEl = newButton;

  buttonEl.className = buttonEl.className.replace("sd-button", "sd-button sd-button-recording");
  buttonEl.innerHTML = `
    <span class="sd-rec-dot sd-rec-dot-uploading"></span>
    <span class="sd-rec-timer sd-rec-upload-label">Uploading…</span>
  `;

  buttonEl.onclick = (e) => e.preventDefault();
}

/**
 * Update the upload progress percentage on the FAB.
 */
export function updatePopupUploadProgress(percent: number): void {
  if (!buttonEl) return;
  const label = buttonEl.querySelector(".sd-rec-upload-label");
  if (label) {
    label.textContent = percent < 100 ? `Uploading… ${percent}%` : "Processing…";
  }
}

function formatElapsed(seconds: number): string {
  const min = Math.floor(seconds / 60);
  const sec = seconds % 60;
  return `${min}:${sec.toString().padStart(2, "0")}`;
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
