/**
 * Capture step: adaptive textarea + video/screenshot capture tools.
 *
 * Shows a description textarea with an issue-type-dependent placeholder,
 * capture tool buttons based on getCaptureOptions(), and manages the
 * full video recording lifecycle (toggles, start, floating bar, stop, preview).
 */

import type { WizardState } from "./wizard-state";
import { getCaptureOptions, getTextareaPlaceholder } from "./wizard-state";
import type { ShowdeskConfig } from "../../types";
import { ScreenRecorder } from "../../recorder/screen-recorder";

export function renderCaptureStep(
  container: HTMLElement,
  state: WizardState,
  _config: ShowdeskConfig,
  onComplete: (updates: Partial<WizardState>) => void,
  onBack: () => void,
): void {
  container.innerHTML = "";

  const options = getCaptureOptions(state);
  const recorder = new ScreenRecorder();

  let currentBlob: Blob | null = state.recordedBlob;
  let audioEnabled = state.hasAudio;
  let cameraEnabled = state.hasCamera;
  let recordingStartTime = 0;
  let timerInterval: ReturnType<typeof setInterval> | null = null;

  const wrapper = document.createElement("div");
  wrapper.className = "sd-wizard-step";

  // Title
  const title = document.createElement("h3");
  title.className = "sd-wizard-title";
  title.textContent = "Describe your issue";
  wrapper.appendChild(title);

  // Textarea
  const fieldDiv = document.createElement("div");
  fieldDiv.className = "sd-field";

  const textarea = document.createElement("textarea");
  textarea.className = "sd-capture-textarea";
  textarea.placeholder = getTextareaPlaceholder(state.issueType);
  textarea.value = state.description;
  textarea.rows = 4;
  textarea.addEventListener("input", () => {
    updateContinueButton();
  });
  fieldDiv.appendChild(textarea);
  wrapper.appendChild(fieldDiv);

  // Capture tools
  const toolsDiv = document.createElement("div");
  toolsDiv.className = "sd-recorder-controls";

  if (options.showVideo) {
    const videoBtn = document.createElement("button");
    videoBtn.className = "sd-recorder-btn";
    videoBtn.innerHTML = `<span>\uD83C\uDFA5</span> Video`;
    if (options.videoRecommended) {
      videoBtn.innerHTML += ` <span class="sd-recommended-badge">Recommended</span>`;
    }
    videoBtn.addEventListener("click", () => {
      showRecordingPanel();
    });
    toolsDiv.appendChild(videoBtn);
  }

  if (options.showScreenshot) {
    const screenshotBtn = document.createElement("button");
    screenshotBtn.className = "sd-recorder-btn";
    screenshotBtn.disabled = true;
    screenshotBtn.innerHTML = `<span>\uD83D\uDCF7</span> Screenshot`;
    screenshotBtn.title = "Coming soon";
    toolsDiv.appendChild(screenshotBtn);
  }

  wrapper.appendChild(toolsDiv);

  // Recording panel (hidden by default)
  const recordingPanel = document.createElement("div");
  recordingPanel.className = "sd-recording-panel";
  recordingPanel.style.display = "none";
  wrapper.appendChild(recordingPanel);

  // Preview section (shown after recording)
  const previewSection = document.createElement("div");
  previewSection.className = "sd-recording-preview";
  previewSection.style.display = "none";
  wrapper.appendChild(previewSection);

  // Show existing recording preview if blob exists
  if (currentBlob) {
    renderPreview();
  }

  // Action buttons
  const actionsDiv = document.createElement("div");
  actionsDiv.className = "sd-wizard-actions";

  const backBtn = document.createElement("button");
  backBtn.className = "sd-back-btn";
  backBtn.textContent = "\u25C0 Back";
  backBtn.addEventListener("click", onBack);

  const continueBtn = document.createElement("button");
  continueBtn.className = "sd-submit-btn";
  continueBtn.textContent = "Continue";
  continueBtn.disabled = true;
  continueBtn.addEventListener("click", () => {
    onComplete({
      description: textarea.value.trim(),
      recordedBlob: currentBlob,
      hasAudio: audioEnabled,
      hasCamera: cameraEnabled,
    });
  });

  actionsDiv.appendChild(backBtn);
  actionsDiv.appendChild(continueBtn);
  wrapper.appendChild(actionsDiv);

  container.appendChild(wrapper);
  updateContinueButton();

  // --- Helper functions ---

  function updateContinueButton(): void {
    continueBtn.disabled = textarea.value.trim().length === 0;
  }

  function showRecordingPanel(): void {
    recordingPanel.style.display = "block";
    recordingPanel.innerHTML = "";

    // Mic toggle
    if (options.showMic) {
      const micToggle = createToggle("\uD83C\uDF99\uFE0F Microphone", audioEnabled, (val) => {
        audioEnabled = val;
      });
      recordingPanel.appendChild(micToggle);
    }

    // Camera toggle
    if (options.showCamera) {
      const camToggle = createToggle("\uD83D\uDCF9 Camera", cameraEnabled, (val) => {
        cameraEnabled = val;
      });
      recordingPanel.appendChild(camToggle);
    }

    // Start recording button
    const startBtn = document.createElement("button");
    startBtn.className = "sd-submit-btn";
    startBtn.style.marginTop = "8px";
    startBtn.textContent = "Start recording";
    startBtn.addEventListener("click", () => {
      void startRecording();
    });
    recordingPanel.appendChild(startBtn);
  }

  async function startRecording(): Promise<void> {
    try {
      recorder.onStop = (blob: Blob) => {
        currentBlob = blob;
        removeFloatingBar();
        // Show the modal content again
        wrapper.style.display = "block";
        recordingPanel.style.display = "none";
        renderPreview();
        updateContinueButton();
      };

      await recorder.start({ audio: audioEnabled, camera: cameraEnabled });
      recordingStartTime = Date.now();

      // Hide modal content and show floating recording bar
      wrapper.style.display = "none";
      showFloatingBar();
    } catch (err) {
      const errorDiv = document.createElement("div");
      errorDiv.className = "sd-error";
      errorDiv.textContent = `Could not start recording: ${err instanceof Error ? err.message : "Unknown error"}`;
      recordingPanel.appendChild(errorDiv);
    }
  }

  function showFloatingBar(): void {
    const bar = document.createElement("div");
    bar.id = "sd-floating-recording-bar";
    bar.style.cssText = `
      position: fixed;
      bottom: 24px;
      left: 50%;
      transform: translateX(-50%);
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 12px 20px;
      background: #1f2937;
      color: white;
      border-radius: 50px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
      z-index: 2147483647;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      font-size: 14px;
    `;

    const dot = document.createElement("span");
    dot.style.cssText = `
      width: 10px;
      height: 10px;
      background: #ef4444;
      border-radius: 50%;
      animation: sd-pulse 1s infinite;
    `;
    bar.appendChild(dot);

    const timerSpan = document.createElement("span");
    timerSpan.textContent = "0:00";
    bar.appendChild(timerSpan);

    timerInterval = setInterval(() => {
      const elapsed = Math.floor((Date.now() - recordingStartTime) / 1000);
      const mins = Math.floor(elapsed / 60);
      const secs = elapsed % 60;
      timerSpan.textContent = `${mins}:${secs.toString().padStart(2, "0")}`;
    }, 1000);

    const stopBtn = document.createElement("button");
    stopBtn.textContent = "Stop";
    stopBtn.style.cssText = `
      padding: 6px 16px;
      background: #ef4444;
      color: white;
      border: none;
      border-radius: 20px;
      cursor: pointer;
      font-size: 13px;
      font-weight: 600;
    `;
    stopBtn.addEventListener("click", () => {
      recorder.stop();
    });
    bar.appendChild(stopBtn);

    document.body.appendChild(bar);
  }

  function removeFloatingBar(): void {
    if (timerInterval) {
      clearInterval(timerInterval);
      timerInterval = null;
    }
    const bar = document.getElementById("sd-floating-recording-bar");
    if (bar) {
      bar.remove();
    }
  }

  function renderPreview(): void {
    if (!currentBlob) return;

    previewSection.style.display = "block";
    previewSection.innerHTML = "";

    const previewCard = document.createElement("div");
    previewCard.className = "sd-recording-indicator";

    const elapsed = recordingStartTime
      ? Math.floor((Date.now() - recordingStartTime) / 1000)
      : 0;
    const sizeMB = (currentBlob.size / (1024 * 1024)).toFixed(1);
    const mins = Math.floor(elapsed / 60);
    const secs = elapsed % 60;
    const durationStr = elapsed > 0
      ? `${mins}:${secs.toString().padStart(2, "0")}`
      : "recorded";

    const infoSpan = document.createElement("span");
    infoSpan.textContent = `recording.webm - ${durationStr} - ${sizeMB} MB`;
    previewCard.appendChild(infoSpan);

    const removeBtn = document.createElement("button");
    removeBtn.className = "sd-back-btn";
    removeBtn.textContent = "Remove";
    removeBtn.style.marginLeft = "auto";
    removeBtn.addEventListener("click", () => {
      currentBlob = null;
      previewSection.style.display = "none";
      previewSection.innerHTML = "";
    });
    previewCard.appendChild(removeBtn);

    previewSection.appendChild(previewCard);
  }

  function createToggle(
    label: string,
    initialValue: boolean,
    onChange: (value: boolean) => void,
  ): HTMLElement {
    const row = document.createElement("label");
    row.style.cssText = `
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 6px 0;
      cursor: pointer;
      font-size: 13px;
    `;

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = initialValue;
    checkbox.addEventListener("change", () => {
      onChange(checkbox.checked);
    });

    const text = document.createElement("span");
    text.textContent = label;

    row.appendChild(checkbox);
    row.appendChild(text);
    return row;
  }
}
