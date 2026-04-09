/**
 * Message Input — Text input bar + media toolbar at the bottom of the chat.
 *
 * Features:
 * - Auto-expanding textarea
 * - Send button
 * - Attachment button → popup menu (screenshot, file, video, audio)
 * - Inline audio recording indicator
 */

import { createAudioRecorder } from "./audio-recorder";
import { renderAttachmentMenu } from "./attachment-menu";

export interface MessageInputCallbacks {
  onSendText: (text: string) => void;
  onSendAudio: (blob: Blob) => void;
  onScreenshot: () => void;
  onFile: (file: File) => void;
  onVideo: () => void;
}

export function renderMessageInput(
  callbacks: MessageInputCallbacks,
): HTMLElement {
  const container = document.createElement("div");
  container.className = "sd-input-bar";

  // Audio recording state
  const audioRecorder = createAudioRecorder((recording, duration) => {
    if (recording) {
      showRecordingUI(duration);
    } else {
      hideRecordingUI();
    }
  });

  // Recording indicator (hidden by default)
  const recordingIndicator = document.createElement("div");
  recordingIndicator.className = "sd-recording-inline";
  recordingIndicator.style.display = "none";
  recordingIndicator.innerHTML = `
    <span class="sd-recording-dot"></span>
    <span class="sd-recording-timer">0:00</span>
    <button class="sd-recording-stop" title="Stop">Stop</button>
  `;

  const stopBtn = recordingIndicator.querySelector(
    ".sd-recording-stop",
  ) as HTMLButtonElement;
  stopBtn.onclick = () => {
    const blob = audioRecorder.stop();
    if (blob) callbacks.onSendAudio(blob);
  };

  // Input row
  const inputRow = document.createElement("div");
  inputRow.className = "sd-input-row";

  // Attachment button
  const attachBtn = document.createElement("button");
  attachBtn.className = "sd-input-attach";
  attachBtn.innerHTML = "+";
  attachBtn.title = "Attach media";

  // Hidden file input
  const fileInput = document.createElement("input");
  fileInput.type = "file";
  fileInput.style.display = "none";
  fileInput.accept = "image/*,.pdf,.doc,.docx,.txt,.csv,.xls,.xlsx";
  fileInput.onchange = () => {
    const file = fileInput.files?.[0];
    if (file) {
      callbacks.onFile(file);
      fileInput.value = "";
    }
  };

  attachBtn.onclick = (e) => {
    e.stopPropagation();
    const menuContainer = container.querySelector(".sd-input-attach-wrapper") as HTMLElement;
    const menu = renderAttachmentMenu(
      {
        onScreenshot: callbacks.onScreenshot,
        onFile: () => fileInput.click(),
        onVideo: callbacks.onVideo,
        onAudio: async () => {
          if (audioRecorder.isRecording()) {
            const blob = audioRecorder.stop();
            if (blob) callbacks.onSendAudio(blob);
          } else {
            const ok = await audioRecorder.start();
            if (!ok) {
              console.warn("[Showdesk] Microphone permission denied.");
            }
          }
        },
      },
      attachBtn,
    );
    menuContainer.appendChild(menu);
  };

  const attachWrapper = document.createElement("div");
  attachWrapper.className = "sd-input-attach-wrapper";
  attachWrapper.appendChild(attachBtn);
  attachWrapper.appendChild(fileInput);

  // Textarea
  const textarea = document.createElement("textarea");
  textarea.className = "sd-input-textarea";
  textarea.placeholder = "Type a message...";
  textarea.rows = 1;

  // Auto-expand
  textarea.addEventListener("input", () => {
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 80)}px`;
  });

  // Enter to send (Shift+Enter for newline)
  textarea.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });

  // Send button
  const sendBtn = document.createElement("button");
  sendBtn.className = "sd-input-send";
  sendBtn.innerHTML = `<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>`;
  sendBtn.title = "Send";
  sendBtn.onclick = () => send();

  function send(): void {
    const text = textarea.value.trim();
    if (!text) return;
    callbacks.onSendText(text);
    textarea.value = "";
    textarea.style.height = "auto";
  }

  function showRecordingUI(duration: number): void {
    recordingIndicator.style.display = "flex";
    inputRow.style.display = "none";
    const timer = recordingIndicator.querySelector(
      ".sd-recording-timer",
    ) as HTMLElement;
    const mins = Math.floor(duration / 60);
    const secs = duration % 60;
    timer.textContent = `${mins}:${secs.toString().padStart(2, "0")}`;
  }

  function hideRecordingUI(): void {
    recordingIndicator.style.display = "none";
    inputRow.style.display = "flex";
  }

  inputRow.appendChild(attachWrapper);
  inputRow.appendChild(textarea);
  inputRow.appendChild(sendBtn);

  container.appendChild(recordingIndicator);
  container.appendChild(inputRow);

  return container;
}
