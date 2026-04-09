/**
 * Wizard-based ticket submission modal.
 *
 * Orchestrates a multi-step flow:
 *   Qualification -> Capture -> Contact/Recap -> Sending -> Confirmation
 *
 * Context is captured at submission time (not modal open time) so that
 * the freshest console/network errors are included.
 */

import type { ShowdeskConfig } from "../types";
import { createInitialState, canSkipContact } from "./wizard/wizard-state";
import type { WizardStep } from "./wizard/wizard-state";
import { renderQualificationStep } from "./wizard/step-qualification";
import { renderCaptureStep } from "./wizard/step-capture";
import { renderContactStep } from "./wizard/step-contact";
import { renderConfirmationStep } from "./wizard/step-confirmation";
import { captureContext } from "../api/context";
import { submitTicket, uploadAttachment, uploadVideo } from "../api/submit";
import { clearConsoleEntries } from "../collectors/console-collector";
import { clearNetworkEntries } from "../collectors/network-collector";
import type { ScreenRecorder } from "../recorder/screen-recorder";

export function createModal(config: ShowdeskConfig): void {
  // Remove existing modal if any
  const existing = document.getElementById("showdesk-modal-overlay");
  if (existing) existing.remove();

  const container = document.getElementById("showdesk-widget-container");
  if (!container) return;

  // Track active screen recorder so we can clean up on modal close
  let activeRecorder: ScreenRecorder | null = null;

  // Initialize wizard state with pre-filled user info
  const state = createInitialState(
    config.user?.name || "",
    config.user?.email || "",
  );

  // Create overlay
  const overlay = document.createElement("div");
  overlay.id = "showdesk-modal-overlay";
  overlay.className = "sd-overlay";
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeModal();
  });

  // Create modal shell
  const modal = document.createElement("div");
  modal.className = "sd-modal";
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-label", "Submit a support ticket");

  // Header with step indicator + close button
  const header = document.createElement("div");
  header.className = "sd-modal-header";

  const stepIndicator = document.createElement("div");
  stepIndicator.className = "sd-step-dots";
  for (let i = 0; i < 4; i++) {
    const dot = document.createElement("span");
    dot.className = "sd-step-dot";
    stepIndicator.appendChild(dot);
  }
  header.appendChild(stepIndicator);

  const closeBtn = document.createElement("button");
  closeBtn.className = "sd-modal-close";
  closeBtn.setAttribute("aria-label", "Close");
  closeBtn.innerHTML = "&times;";
  closeBtn.addEventListener("click", closeModal);
  header.appendChild(closeBtn);

  modal.appendChild(header);

  // Content area
  const contentEl = document.createElement("div");
  contentEl.className = "sd-modal-body";
  modal.appendChild(contentEl);

  overlay.appendChild(modal);
  container.appendChild(overlay);

  // Escape key handler
  function onKeyDown(e: KeyboardEvent): void {
    if (e.key === "Escape") closeModal();
  }
  document.addEventListener("keydown", onKeyDown);

  function closeModal(): void {
    // Stop any active recording and clean up streams
    if (activeRecorder) {
      if (activeRecorder.isRecording) {
        activeRecorder.stop();
      }
      // Remove the floating recording bar if present
      const floatingBar = document.getElementById("sd-floating-recording-bar");
      if (floatingBar) floatingBar.remove();
      // Restore the original FAB button (hidden during recording)
      const fab = document.querySelector<HTMLElement>("#showdesk-widget-container .sd-button");
      if (fab) fab.style.display = "";
      activeRecorder = null;
    }
    document.removeEventListener("keydown", onKeyDown);
    overlay.remove();
  }

  // Update step indicator dots
  function updateStepIndicator(step: WizardStep): void {
    const stepIndex: Record<WizardStep, number> = {
      qualification: 0,
      capture: 1,
      contact: 2,
      sending: 2,
      confirmation: 3,
    };
    const dots = stepIndicator.querySelectorAll(".sd-step-dot");
    dots.forEach((dot, i) => {
      dot.classList.toggle("sd-step-active", i <= stepIndex[step]);
    });
  }

  // --- Step orchestration ---

  function goToQualification(): void {
    state.step = "qualification";
    updateStepIndicator("qualification");
    renderQualificationStep(contentEl, (result) => {
      state.issueType = result.issueType;
      state.bugVisibility = result.bugVisibility;
      goToCapture();
    });
  }

  function goToCapture(): void {
    state.step = "capture";
    updateStepIndicator("capture");
    renderCaptureStep(contentEl, state, config, (updates) => {
      Object.assign(state, updates);
      // Skip contact step if identity is already known
      if (canSkipContact(state.requesterName, state.requesterEmail)) {
        goToSending();
      } else {
        goToContact();
      }
    }, goToQualification, (recorder) => {
      activeRecorder = recorder;
    });
  }

  function goToContact(): void {
    state.step = "contact";
    updateStepIndicator("contact");
    const hasIdentity = canSkipContact(
      config.user?.name || "",
      config.user?.email || "",
    );
    renderContactStep(contentEl, state, hasIdentity, (updates) => {
      Object.assign(state, updates);
      goToSending();
    }, goToCapture);
  }

  async function goToSending(): Promise<void> {
    state.step = "sending";
    updateStepIndicator("sending");
    contentEl.innerHTML = "";

    const wrapper = document.createElement("div");
    wrapper.className = "sd-wizard-step";
    wrapper.style.textAlign = "center";
    wrapper.style.padding = "48px 24px";

    const spinner = document.createElement("div");
    spinner.className = "sd-loading-spinner";
    wrapper.appendChild(spinner);

    const statusText = document.createElement("p");
    statusText.style.marginTop = "16px";
    statusText.style.color = "var(--sd-text-light)";
    statusText.textContent = "Sending your message...";
    wrapper.appendChild(statusText);

    contentEl.appendChild(wrapper);

    try {
      // Capture context at submission time for freshest error data
      const context = captureContext();
      clearConsoleEntries();
      clearNetworkEntries();

      const ticketData = {
        title: state.description.slice(0, 100),
        description: state.description,
        requester_name: state.requesterName,
        requester_email: state.requesterEmail,
        priority: "medium",
        issue_type: state.issueType || "other",
        external_user_id: config.user?.id || "",
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
      };

      const ticket = await submitTicket(config, ticketData);

      // Upload video if recorded
      if (state.recordedBlob && ticket.id) {
        statusText.textContent = "Uploading video...";
        await uploadVideo(config, ticket.id, state.recordedBlob, {
          hasAudio: state.hasAudio,
          hasCamera: state.hasCamera,
          onProgress: (percent: number) => {
            statusText.textContent = `Uploading video... ${Math.round(percent)}%`;
          },
        });
      }

      // Upload file attachments (screenshots, etc.)
      if (state.attachments.length > 0 && ticket.id) {
        for (let i = 0; i < state.attachments.length; i++) {
          const file = state.attachments[i];
          if (!file) continue;
          statusText.textContent = `Uploading attachment ${i + 1}/${state.attachments.length}...`;
          await uploadAttachment(config, ticket.id, file);
        }
      }

      goToConfirmation(ticket.reference ?? "");
    } catch (err) {
      console.error("[Showdesk] Submission failed:", err);

      wrapper.innerHTML = "";
      const errorDiv = document.createElement("div");
      errorDiv.className = "sd-error";
      errorDiv.textContent = "Something went wrong. Please try again.";
      wrapper.appendChild(errorDiv);

      const retryBtn = document.createElement("button");
      retryBtn.className = "sd-submit-btn";
      retryBtn.style.marginTop = "12px";
      retryBtn.textContent = "Retry";
      retryBtn.addEventListener("click", () => {
        void goToSending();
      });
      wrapper.appendChild(retryBtn);

      const backBtn = document.createElement("button");
      backBtn.className = "sd-back-btn";
      backBtn.style.marginTop = "8px";
      backBtn.textContent = "\u25C0 Back";
      backBtn.addEventListener("click", goToCapture);
      wrapper.appendChild(backBtn);
    }
  }

  function goToConfirmation(ticketReference: string): void {
    state.step = "confirmation";
    updateStepIndicator("confirmation");
    renderConfirmationStep(contentEl, ticketReference, closeModal);
  }

  // Start the wizard
  goToQualification();
}
