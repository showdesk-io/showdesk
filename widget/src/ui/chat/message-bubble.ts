/**
 * Message Bubble — Renders a single message in the chat thread.
 *
 * Handles different body types: text, image/screenshot, audio, video.
 * Media clicks open a lightbox instead of a new tab.
 * Supports local blob URLs for immediate preview of optimistic messages.
 */

import type { ChatMessage } from "../../types";
import { openLightbox } from "../media-lightbox";

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
    case "file":
      bubble.appendChild(renderFile(msg));
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

/** Get the best available URL: server attachment or local blob. */
function getMediaUrl(msg: ChatMessage): string | null {
  return msg.attachments[0]?.url || msg._localUrl || null;
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
  const url = getMediaUrl(msg);
  if (url) {
    const audio = document.createElement("audio");
    audio.controls = true;
    audio.preload = "metadata";
    audio.src = url;
    el.appendChild(audio);
    // Click on the container (not controls) opens lightbox
    el.addEventListener("click", (e) => {
      if ((e.target as HTMLElement).tagName !== "AUDIO") {
        openLightbox(url, "audio");
      }
    });
  } else {
    el.textContent = "🎤 Audio message";
  }
  return el;
}

function renderImage(msg: ChatMessage): HTMLElement {
  const el = document.createElement("div");
  el.className = "sd-msg-image";
  const url = getMediaUrl(msg);
  if (url) {
    const img = document.createElement("img");
    img.src = url;
    img.alt = msg.bodyType === "screenshot" ? "Screenshot" : "Image";
    img.loading = "lazy";
    img.style.cursor = "pointer";
    img.onclick = () => openLightbox(url, msg.bodyType as "image" | "screenshot", img.alt);
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
  const url = getMediaUrl(msg);
  if (url) {
    const video = document.createElement("video");
    video.controls = true;
    video.preload = "metadata";
    video.src = url;
    // Click on the video poster/thumbnail area opens lightbox
    const overlay = document.createElement("div");
    overlay.className = "sd-msg-video-expand";
    overlay.innerHTML = "⛶";
    overlay.title = "Expand";
    overlay.onclick = (e) => {
      e.stopPropagation();
      video.pause();
      openLightbox(url, "video");
    };
    el.appendChild(video);
    el.appendChild(overlay);
  } else {
    el.textContent = "🎬 Screen capture";
  }
  return el;
}

function renderFile(msg: ChatMessage): HTMLElement {
  const el = document.createElement("div");
  el.className = "sd-msg-file";
  const url = getMediaUrl(msg);
  const filename = msg.attachments[0]?.filename || msg.body || "File";

  const icon = document.createElement("span");
  icon.className = "sd-msg-file-icon";
  icon.textContent = "📄";

  const name = document.createElement("span");
  name.className = "sd-msg-file-name";
  name.textContent = filename;

  if (url) {
    const link = document.createElement("a");
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener";
    link.className = "sd-msg-file-link";
    link.appendChild(icon);
    link.appendChild(name);
    el.appendChild(link);
  } else {
    el.appendChild(icon);
    el.appendChild(name);
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
