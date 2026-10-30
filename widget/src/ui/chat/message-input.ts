/**
 * Message Input — Text input bar + media toolbar at the bottom of the chat.
 *
 * Features:
 * - Auto-expanding textarea
 * - Send button
 * - Attachment button → popup menu (screenshot, file, video, audio)
 * - Inline audio recording indicator
 */

import { renderAttachmentMenu } from "./attachment-menu";

const INPUT_ERROR_CLASS = "sd-input-error";

/** Say, above the input, that what the user tried to send didn't leave. */
export function showSendError(): void {
  const bar = document.querySelector(".sd-input-bar");
  if (!bar) return;
  clearSendError();
  const error = document.createElement("div");
  error.className = INPUT_ERROR_CLASS;
  error.setAttribute("role", "alert");
  error.textContent =
    "Your message couldn't be sent. Check your connection and try again.";
  bar.prepend(error);
}

export function clearSendError(): void {
  document.querySelector(`.${INPUT_ERROR_CLASS}`)?.remove();
}

export interface MessageInputCallbacks {
  /**
   * True if the text is on its way. A promise if that takes waiting for a session: the
   * input keeps the text meanwhile, and after if the answer is false.
   */
  onSendText: (text: string) => true | Promise<boolean>;
  onSendAudio: () => void;
  onScreenshot: () => void;
  onFile: (file: File) => void;
  onVideo: () => void;
}

export function renderMessageInput(
  callbacks: MessageInputCallbacks,
): HTMLElement {
  const container = document.createElement("div");
  container.className = "sd-input-bar";

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
        onAudio: () => callbacks.onSendAudio(),
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

  let waiting = false;

  function clearInput(): void {
    textarea.value = "";
    textarea.style.height = "auto";
  }

  function setWaiting(value: boolean): void {
    waiting = value;
    textarea.readOnly = value;
    sendBtn.disabled = value;
  }

  function send(): void {
    const text = textarea.value.trim();
    if (!text || waiting) return;
    clearSendError();
    const accepted = callbacks.onSendText(text);
    if (accepted === true) {
      clearInput();
      return;
    }
    setWaiting(true);
    void accepted.then((sent) => {
      setWaiting(false);
      if (sent) clearInput();
      else showSendError();
    });
  }

  inputRow.appendChild(attachWrapper);
  inputRow.appendChild(textarea);
  inputRow.appendChild(sendBtn);

  container.appendChild(inputRow);

  return container;
}
