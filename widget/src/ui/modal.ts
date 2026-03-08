/**
 * Ticket submission modal.
 *
 * The modal is the core user experience. It combines a traditional
 * text form with video recording controls, embodying the "Show,
 * don't type" philosophy. The video option is always prominent,
 * never hidden behind a menu.
 */

import type { ShowdeskConfig, TechnicalContext } from "../types";
import { ScreenRecorder } from "../recorder/screen-recorder";
import { submitTicket, uploadVideo } from "../api/submit";

export function createModal(
  config: ShowdeskConfig,
  context: TechnicalContext,
): void {
  // Remove existing modal if any
  const existing = document.getElementById("showdesk-modal-overlay");
  if (existing) existing.remove();

  const container = document.getElementById("showdesk-widget-container");
  if (!container) return;

  // Create overlay
  const overlay = document.createElement("div");
  overlay.id = "showdesk-modal-overlay";
  overlay.className = "sd-overlay";
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeModal();
  });

  // Create modal
  const modal = document.createElement("div");
  modal.className = "sd-modal";
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-label", "Submit a support ticket");

  const recorder = new ScreenRecorder();
  let recordedBlob: Blob | null = null;

  modal.innerHTML = `
    <div class="sd-modal-header">
      <h2>${escapeHtml(config.greeting)}</h2>
      <button class="sd-modal-close" aria-label="Close">&times;</button>
    </div>
    <div class="sd-modal-body">
      <div class="sd-field">
        <label for="sd-name">Your name</label>
        <input type="text" id="sd-name" placeholder="Jane Doe" required />
      </div>
      <div class="sd-field">
        <label for="sd-email">Email</label>
        <input type="email" id="sd-email" placeholder="jane@company.com" required />
      </div>
      <div class="sd-field">
        <label for="sd-title">Subject</label>
        <input type="text" id="sd-title" placeholder="Brief description of your issue" required />
      </div>
      <div class="sd-field">
        <label for="sd-description">Details</label>
        <textarea id="sd-description" placeholder="Describe what happened..."></textarea>
      </div>

      <div class="sd-recorder-controls">
        <button class="sd-recorder-btn" id="sd-record-screen" type="button">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>
            <line x1="8" y1="21" x2="16" y2="21"/>
            <line x1="12" y1="17" x2="12" y2="21"/>
          </svg>
          Record Screen
        </button>
        <button class="sd-recorder-btn" id="sd-toggle-camera" type="button">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M23 7l-7 5 7 5V7z"/>
            <rect x="1" y="5" width="15" height="14" rx="2" ry="2"/>
          </svg>
          Camera
        </button>
        <button class="sd-recorder-btn" id="sd-toggle-mic" type="button">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
            <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
            <line x1="12" y1="19" x2="12" y2="23"/>
          </svg>
          Mic
        </button>
      </div>

      <div id="sd-recording-status" style="display:none">
        <div class="sd-recording-indicator">
          <div class="sd-recording-dot"></div>
          <span>Recording... <span id="sd-recording-time">0:00</span></span>
          <button class="sd-recorder-btn" id="sd-stop-recording" type="button" style="margin-left:auto">
            Stop
          </button>
        </div>
      </div>

      <div id="sd-recording-preview" style="display:none; margin-bottom: 16px;">
        <video id="sd-preview-video" style="width:100%; border-radius:8px; background:#000;" controls></video>
      </div>

      <div id="sd-error-message" class="sd-error" style="display:none"></div>

      <div id="sd-upload-progress" style="display:none; margin-bottom: 16px;">
        <div style="display:flex; align-items:center; gap:8px; font-size:13px; color:var(--sd-text-light);">
          <span>Uploading video...</span>
          <span id="sd-upload-percent">0%</span>
        </div>
        <div style="height:4px; background:#e5e7eb; border-radius:4px; margin-top:6px; overflow:hidden;">
          <div id="sd-upload-bar" style="height:100%; background:var(--sd-primary); width:0%; transition:width 0.3s;"></div>
        </div>
      </div>

      <div class="sd-field" style="margin-bottom:12px;">
        <label class="sd-recorder-btn" id="sd-file-label" style="cursor:pointer; display:inline-flex; width:auto;">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/>
          </svg>
          Attach file
          <input type="file" id="sd-file-input" class="sd-file-input" multiple />
        </label>
        <span id="sd-file-names" style="font-size:12px; color:var(--sd-text-light); margin-left:8px;"></span>
      </div>

      <button class="sd-submit-btn" id="sd-submit" type="button">
        Submit Ticket
      </button>
    </div>
  `;

  overlay.appendChild(modal);
  container.appendChild(overlay);

  // Event handlers
  const closeBtn = modal.querySelector(".sd-modal-close") as HTMLButtonElement;
  closeBtn.addEventListener("click", closeModal);

  const recordBtn = modal.querySelector("#sd-record-screen") as HTMLButtonElement;
  const cameraBtn = modal.querySelector("#sd-toggle-camera") as HTMLButtonElement;
  const micBtn = modal.querySelector("#sd-toggle-mic") as HTMLButtonElement;
  const stopBtn = modal.querySelector("#sd-stop-recording") as HTMLButtonElement;
  const submitBtn = modal.querySelector("#sd-submit") as HTMLButtonElement;

  const fileInput = modal.querySelector("#sd-file-input") as HTMLInputElement;
  const fileNamesEl = modal.querySelector("#sd-file-names") as HTMLElement;
  const errorEl = modal.querySelector("#sd-error-message") as HTMLElement;

  let enableCamera = false;
  let enableMic = true;
  let selectedFiles: File[] = [];

  cameraBtn.addEventListener("click", () => {
    enableCamera = !enableCamera;
    cameraBtn.classList.toggle("active", enableCamera);
  });

  micBtn.addEventListener("click", () => {
    enableMic = !enableMic;
    micBtn.classList.toggle("active", enableMic);
  });

  fileInput.addEventListener("change", () => {
    selectedFiles = Array.from(fileInput.files ?? []);
    if (selectedFiles.length > 0) {
      fileNamesEl.textContent = selectedFiles.map((f) => f.name).join(", ");
    } else {
      fileNamesEl.textContent = "";
    }
  });

  // Pre-fill contact fields from user identity
  const nameInput = modal.querySelector("#sd-name") as HTMLInputElement;
  const emailInput = modal.querySelector("#sd-email") as HTMLInputElement;
  nameInput.value = config.user?.name || "";
  emailInput.value = config.user?.email || "";

  // Start mic as active by default
  micBtn.classList.add("active");

  recordBtn.addEventListener("click", async () => {
    try {
      await recorder.start({ audio: enableMic, camera: enableCamera });
      recordBtn.classList.add("recording");
      recordBtn.textContent = "Recording...";

      const statusEl = modal.querySelector("#sd-recording-status") as HTMLElement;
      statusEl.style.display = "block";

      // Start timer
      let seconds = 0;
      const timerEl = modal.querySelector("#sd-recording-time") as HTMLElement;
      const timer = setInterval(() => {
        seconds++;
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        timerEl.textContent = `${mins}:${secs.toString().padStart(2, "0")}`;
      }, 1000);

      recorder.onStop = (blob: Blob) => {
        clearInterval(timer);
        recordedBlob = blob;
        recordBtn.classList.remove("recording");
        recordBtn.textContent = "Re-record";
        statusEl.style.display = "none";

        // Show preview
        const previewContainer = modal.querySelector("#sd-recording-preview") as HTMLElement;
        const previewVideo = modal.querySelector("#sd-preview-video") as HTMLVideoElement;
        previewContainer.style.display = "block";
        previewVideo.src = URL.createObjectURL(blob);
      };
    } catch (err) {
      console.error("[Showdesk] Recording failed:", err);
    }
  });

  stopBtn.addEventListener("click", () => {
    recorder.stop();
  });

  submitBtn.addEventListener("click", async () => {
    const name = (modal.querySelector("#sd-name") as HTMLInputElement).value.trim();
    const email = (modal.querySelector("#sd-email") as HTMLInputElement).value.trim();
    const title = (modal.querySelector("#sd-title") as HTMLInputElement).value.trim();
    const description = (modal.querySelector("#sd-description") as HTMLTextAreaElement).value.trim();

    // Clear previous errors
    errorEl.style.display = "none";
    errorEl.textContent = "";

    // Validate required fields with visual feedback
    const nameInput = modal.querySelector("#sd-name") as HTMLInputElement;
    const emailInput = modal.querySelector("#sd-email") as HTMLInputElement;
    const titleInput = modal.querySelector("#sd-title") as HTMLInputElement;

    [nameInput, emailInput, titleInput].forEach((el) => {
      el.style.borderColor = "";
    });

    const errors: string[] = [];
    if (!name) {
      errors.push("Name is required.");
      nameInput.style.borderColor = "#EF4444";
    }
    if (!email) {
      errors.push("Email is required.");
      emailInput.style.borderColor = "#EF4444";
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      errors.push("Please enter a valid email address.");
      emailInput.style.borderColor = "#EF4444";
    }
    if (!title) {
      errors.push("Subject is required.");
      titleInput.style.borderColor = "#EF4444";
    }

    if (errors.length > 0) {
      errorEl.textContent = errors[0] ?? "";
      errorEl.style.display = "block";
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = "Submitting...";

    try {
      const ticket = await submitTicket(config, {
        title,
        description,
        requester_name: name,
        requester_email: email,
        priority: "medium",
        context_url: context.url,
        context_user_agent: context.userAgent,
        context_os: context.os,
        context_browser: context.browser,
        context_screen_resolution: context.screenResolution,
        context_metadata: {
          language: context.language,
          timezone: context.timezone,
          referrer: context.referrer,
          console_errors: context.consoleErrors,
          network_errors: context.networkErrors,
        },
        external_user_id: config.user?.id || "",
      });

      // Upload video if recorded
      if (recordedBlob && ticket.id) {
        const progressEl = modal.querySelector("#sd-upload-progress") as HTMLElement;
        const progressBar = modal.querySelector("#sd-upload-bar") as HTMLElement;
        const progressPercent = modal.querySelector("#sd-upload-percent") as HTMLElement;
        progressEl.style.display = "block";
        submitBtn.textContent = "Uploading video...";

        await uploadVideo(config, ticket.id, recordedBlob, {
          hasAudio: enableMic,
          hasCamera: enableCamera,
          onProgress: (percent: number) => {
            progressBar.style.width = `${percent}%`;
            progressPercent.textContent = `${Math.round(percent)}%`;
          },
        });
      }

      // Show success
      const body = modal.querySelector(".sd-modal-body") as HTMLElement;
      body.innerHTML = `
        <div class="sd-success">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" style="margin:0 auto;">
            <circle cx="12" cy="12" r="10"/>
            <path d="M9 12l2 2 4-4"/>
          </svg>
          <h3>Ticket submitted!</h3>
          <p>Reference: ${escapeHtml(ticket.reference ?? "")}</p>
          <p style="margin-top:8px">We'll get back to you soon.</p>
        </div>
      `;

      // Auto-close after delay
      setTimeout(closeModal, 4000);
    } catch (err) {
      console.error("[Showdesk] Submission failed:", err);
      errorEl.textContent = "Something went wrong. Please try again.";
      errorEl.style.display = "block";
      submitBtn.disabled = false;
      submitBtn.textContent = "Submit Ticket";
    }
  });

  function closeModal(): void {
    recorder.stop();
    overlay.remove();
  }
}

function escapeHtml(text: string): string {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}
