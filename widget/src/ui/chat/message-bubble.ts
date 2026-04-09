/**
 * Message Bubble — Renders a single message in the chat thread.
 *
 * Handles different body types: text, image/screenshot, audio, video.
 */

import type { ChatMessage } from "../../types";

export function renderMessageBubble(msg: ChatMessage): HTMLElement {
  const isUser = msg.senderType === "user";
  const isSystem = msg.senderType === "system";

  const wrapper = document.createElement("div");
  wrapper.className = `sd-msg ${isUser ? "sd-msg-user" : isSystem ? "sd-msg-system" : "sd-msg-agent"}`;
  wrapper.dataset.messageId = msg.id;

  if (isSystem) {
    wrapper.innerHTML = `<div class="sd-msg-system-text">${escapeHtml(msg.body)}</div>`;
    return wrapper;
  }

  const bubble = document.createElement("div");
  bubble.className = "sd-msg-bubble";

  // Render by body type
  switch (msg.bodyType) {
    case "audio":
      bubble.appendChild(renderAudio(msg));
      break;
    case "image":
    case "screenshot":
      bubble.appendChild(renderImage(msg));
      break;
    case "video":
      bubble.appendChild(renderVideo(msg));
      break;
    default:
      bubble.appendChild(renderText(msg));
  }

  // Status indicator for user messages
  if (isUser && msg._status) {
    const statusEl = document.createElement("span");
    statusEl.className = `sd-msg-status sd-msg-status-${msg._status}`;
    statusEl.textContent =
      msg._status === "sending"
        ? "Sending..."
        : msg._status === "failed"
          ? "Failed — tap to retry"
          : "";
    if (statusEl.textContent) bubble.appendChild(statusEl);
  }

  wrapper.appendChild(bubble);

  // Timestamp
  const time = document.createElement("div");
  time.className = "sd-msg-time";
  time.textContent = formatTime(msg.createdAt);
  if (!isUser && msg.senderName) {
    time.textContent = `${msg.senderName} · ${time.textContent}`;
  }
  wrapper.appendChild(time);

  return wrapper;
}

function renderText(msg: ChatMessage): HTMLElement {
  const el = document.createElement("div");
  el.className = "sd-msg-text";
  el.textContent = msg.body;
  return el;
}

function renderAudio(msg: ChatMessage): HTMLElement {
  const el = document.createElement("div");
  el.className = "sd-msg-audio";
  const url = msg.attachments[0]?.url;
  if (url) {
    const audio = document.createElement("audio");
    audio.controls = true;
    audio.preload = "metadata";
    audio.src = url;
    el.appendChild(audio);
  } else {
    el.textContent = "🎤 Audio message";
  }
  return el;
}

function renderImage(msg: ChatMessage): HTMLElement {
  const el = document.createElement("div");
  el.className = "sd-msg-image";
  const url = msg.attachments[0]?.url;
  if (url) {
    const img = document.createElement("img");
    img.src = url;
    img.alt = msg.bodyType === "screenshot" ? "Screenshot" : "Image";
    img.loading = "lazy";
    img.onclick = () => window.open(url, "_blank");
    el.appendChild(img);
  }
  if (msg.body) {
    const caption = document.createElement("div");
    caption.className = "sd-msg-caption";
    caption.textContent = msg.body;
    el.appendChild(caption);
  }
  return el;
}

function renderVideo(msg: ChatMessage): HTMLElement {
  const el = document.createElement("div");
  el.className = "sd-msg-video";
  const url = msg.attachments[0]?.url;
  if (url) {
    const video = document.createElement("video");
    video.controls = true;
    video.preload = "metadata";
    video.src = url;
    el.appendChild(video);
  } else {
    el.textContent = "🎬 Video recording";
  }
  return el;
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

function escapeHtml(str: string): string {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
