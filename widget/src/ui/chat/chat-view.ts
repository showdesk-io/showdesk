/**
 * Chat View — The main messaging interface.
 *
 * Renders the message thread, screenshot suggestion, contact nudge,
 * and message input bar. Handles sending messages and updating state.
 */

import {
  sendMessage,
  sendAttachmentMessage,
  updateSessionContact,
} from "../../api/chat-api";
import { captureContext } from "../../api/context";
import type { WidgetStore } from "../../state/widget-state";
import type { ChatMessage, ShowdeskConfig } from "../../types";
import {
  showRecordingController,
  showPopupRecordingController,
  hideRecordingController,
} from "../button";
import { renderContactNudge } from "./contact-nudge";
import { renderMessageBubble } from "./message-bubble";
import { renderMessageInput } from "./message-input";
import { ScreenRecorder } from "../../recorder/screen-recorder";
import type { RecordingMessage } from "../../recorder/broadcast-protocol";
import {
  launchRecorderPopup,
  probeExistingPopup,
  type PopupHandle,
} from "../../recorder/popup-launcher";

let messageListEl: HTMLElement | null = null;

export function renderChatView(
  container: HTMLElement,
  store: WidgetStore,
  config: ShowdeskConfig,
  onOpenPanel?: () => void,
): void {
  container.innerHTML = "";

  // Message list (scrollable)
  messageListEl = document.createElement("div");
  messageListEl.className = "sd-message-list";
  container.appendChild(messageListEl);

  renderMessages(store);

  // Contact nudge (after first message, if anonymous and not dismissed)
  if (shouldShowNudge(store, config)) {
    const nudge = renderContactNudge(store, (name, email) => {
      const session = store.state.session;
      if (session) {
        updateSessionContact(config, session.sessionId, name, email).catch(
          console.error,
        );
        store.update({
          session: { ...session, name, email },
        });
      }
    });
    messageListEl.appendChild(nudge);
    store.update({ contactNudgeShown: true });
    scrollToBottom();
  }

  const openPanel = onOpenPanel ?? (() => {});
  // Message input
  const input = renderMessageInput({
    onSendText: (text) => handleSendText(text, store, config),
    onSendAudio: () => handleAudioCapture(store, config, openPanel),
    onScreenshot: () => handleScreenshotCapture(store, config),
    onFile: (file) => {
      const bodyType = file.type.startsWith("image/") ? "image" : "file";
      handleSendAttachment(file, bodyType, file.name, store, config);
    },
    onVideo: () => handleVideoCapture(store, config, openPanel),
  });
  container.appendChild(input);

  // Subscribe to state changes
  store.subscribe(() => {
    renderMessages(store);
    scrollToBottom();
  });
}

function renderMessages(store: WidgetStore): void {
  if (!messageListEl) return;

  // Build set of current message IDs in state
  const stateIds = new Set(store.state.messages.map((m) => m.id));

  // Remove orphaned DOM elements (e.g. optimistic messages whose ID changed)
  messageListEl.querySelectorAll("[data-message-id]").forEach((el) => {
    const domId = (el as HTMLElement).dataset.messageId!;
    if (!stateIds.has(domId)) {
      el.remove();
    }
  });

  // Collect remaining DOM message IDs
  const existingIds = new Set<string>();
  messageListEl
    .querySelectorAll("[data-message-id]")
    .forEach((el) => existingIds.add((el as HTMLElement).dataset.messageId!));

  for (const msg of store.state.messages) {
    if (existingIds.has(msg.id)) {
      // Update status if changed
      const existing = messageListEl.querySelector(
        `[data-message-id="${msg.id}"]`,
      ) as HTMLElement;
      if (existing) {
        const statusEl = existing.querySelector(".sd-msg-status");
        if (statusEl && msg._status === "sent") {
          statusEl.remove();
        }
      }
      continue;
    }
    const bubble = renderMessageBubble(msg);
    messageListEl.appendChild(bubble);
  }

  scrollToBottom();
}

function scrollToBottom(): void {
  if (messageListEl) {
    messageListEl.scrollTop = messageListEl.scrollHeight;
  }
}

function shouldShowNudge(store: WidgetStore, config: ShowdeskConfig): boolean {
  if (store.state.contactNudgeDismissed || store.state.contactNudgeShown) return false;
  if (config.user?.name && config.user?.email) return false;
  if (store.state.session?.name && store.state.session?.email) return false;
  return store.state.messages.some((m) => m.senderType === "user");
}

async function handleSendText(
  text: string,
  store: WidgetStore,
  config: ShowdeskConfig,
): Promise<void> {
  const session = store.state.session;
  if (!session) return;

  // Optimistic message
  const tempId = `temp-${Date.now()}`;
  const optimisticMsg: ChatMessage = {
    id: tempId,
    ticketId: store.state.activeTicketId || "",
    body: text,
    bodyType: "text",
    senderType: "user",
    senderName: session.name,
    attachments: [],
    createdAt: new Date().toISOString(),
    _status: "sending",
  };

  store.update({
    messages: [...store.state.messages, optimisticMsg],
  });

  try {
    // Gather context on first message
    let context: Record<string, unknown> | undefined;
    if (!store.state.activeTicketId) {
      const ctx = captureContext();
      context = {
        url: ctx.url,
        user_agent: ctx.userAgent,
        os: ctx.os,
        browser: ctx.browser,
        screen_resolution: ctx.screenResolution,
        language: ctx.language,
        timezone: ctx.timezone,
        referrer: ctx.referrer,
        console_errors: ctx.consoleErrors,
        network_errors: ctx.networkErrors,
      };
    }

    const result = await sendMessage(
      config,
      session.sessionId,
      store.state.activeTicketId,
      text,
      "text",
      context,
    );

    // Update optimistic message with real data
    const updated = store.state.messages.map((m) =>
      m.id === tempId
        ? { ...m, id: result.messageId, ticketId: result.ticketId, _status: "sent" as const }
        : m,
    );
    store.update({
      messages: updated,
      activeTicketId: result.ticketId,
      activeTicketReference: result.reference,
    });
  } catch {
    // Mark as failed
    const updated = store.state.messages.map((m) =>
      m.id === tempId ? { ...m, _status: "failed" as const } : m,
    );
    store.update({ messages: updated });
  }
}

async function handleSendAttachment(
  blob: Blob | File,
  bodyType: string,
  filename: string,
  store: WidgetStore,
  config: ShowdeskConfig,
): Promise<void> {
  const session = store.state.session;
  if (!session) return;

  // Optimistic message with local blob URL for immediate preview
  const tempId = `temp-${Date.now()}`;
  const localUrl = URL.createObjectURL(blob);
  const optimisticMsg: ChatMessage = {
    id: tempId,
    ticketId: store.state.activeTicketId || "",
    body: "",
    bodyType: bodyType as ChatMessage["bodyType"],
    senderType: "user",
    senderName: session.name,
    attachments: [],
    createdAt: new Date().toISOString(),
    _status: "sending",
    _localUrl: localUrl,
  };

  store.update({
    messages: [...store.state.messages, optimisticMsg],
  });

  try {
    const result = await sendAttachmentMessage(
      config,
      session.sessionId,
      store.state.activeTicketId,
      blob,
      bodyType,
      filename,
    );

    const updated = store.state.messages.map((m) =>
      m.id === tempId
        ? { ...m, id: result.messageId, ticketId: result.ticketId, _status: "sent" as const }
        : m,
    );
    store.update({
      messages: updated,
      activeTicketId: result.ticketId,
      activeTicketReference: result.reference,
    });
  } catch {
    const updated = store.state.messages.map((m) =>
      m.id === tempId ? { ...m, _status: "failed" as const } : m,
    );
    store.update({ messages: updated });
  }
}

async function handleScreenshotCapture(
  store: WidgetStore,
  config: ShowdeskConfig,
): Promise<void> {
  try {
    // Hide the widget panel while capturing
    const panel = document.getElementById("sd-panel");
    if (panel) panel.style.display = "none";

    const stream = await navigator.mediaDevices.getDisplayMedia({
      video: true,
      // @ts-expect-error preferCurrentTab is Chrome-only
      preferCurrentTab: true,
    });

    const track = stream.getVideoTracks()[0];
    if (!track) throw new Error("No video track");
    // @ts-expect-error ImageCapture is not in all TS defs
    const imageCapture = new ImageCapture(track);
    const bitmap = await imageCapture.grabFrame();
    track.stop();

    const canvas = document.createElement("canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const ctx = canvas.getContext("2d")!;
    ctx.drawImage(bitmap, 0, 0);

    const blob = await new Promise<Blob>((resolve) =>
      canvas.toBlob((b) => resolve(b!), "image/png"),
    );

    // Show panel again
    if (panel) panel.style.display = "";

    await handleSendAttachment(blob, "screenshot", "screenshot.png", store, config);
  } catch {
    // User cancelled or API not available
    const panel = document.getElementById("sd-panel");
    if (panel) panel.style.display = "";
  }
}

async function handleAudioCapture(
  store: WidgetStore,
  config: ShowdeskConfig,
  onOpenPanel: () => void,
): Promise<void> {
  try {
    // Hide panel so it doesn't block the page
    const panel = document.getElementById("sd-panel");
    if (panel) panel.style.display = "none";

    // Acquire mic
    let micStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
    });

    // Route mic through AudioContext so we can switch devices
    // without modifying the MediaRecorder's stream (which would stop it).
    const audioCtx = new AudioContext();
    const audioDest = audioCtx.createMediaStreamDestination();
    let micSource = audioCtx.createMediaStreamSource(micStream);
    micSource.connect(audioDest);
    let currentMicDeviceId = "";

    const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : "audio/webm";

    const chunks: Blob[] = [];
    // Record from the AudioContext destination, not the raw mic stream
    const recorder = new MediaRecorder(audioDest.stream, { mimeType });

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.push(e.data);
    };

    recorder.onstop = () => {
      micSource.disconnect();
      audioDest.stream.getTracks().forEach((t) => t.stop());
      micStream.getTracks().forEach((t) => t.stop());
      audioCtx.close().catch(() => {});
      hideRecordingController(onOpenPanel);
      if (panel) panel.style.display = "";
      if (chunks.length > 0) {
        const blob = new Blob(chunks, { type: mimeType });
        handleSendAttachment(blob, "audio", "audio.webm", store, config);
      }
    };

    recorder.start(100);

    // Show FAB controller with mic selection
    showRecordingController({
      onStop: () => recorder.stop(),
      onToggleAudio: () => {
        const tracks = audioDest.stream.getAudioTracks();
        const newEnabled = !tracks.some((t) => t.enabled);
        tracks.forEach((t) => { t.enabled = newEnabled; });
        return newEnabled;
      },
      onSwitchMic: async (deviceId) => {
        currentMicDeviceId = deviceId;
        try {
          const newStream = await navigator.mediaDevices.getUserMedia({
            audio: {
              deviceId: { exact: deviceId },
              echoCancellation: true,
              noiseSuppression: true,
            },
          });
          // Disconnect old source, connect new one to same destination.
          // MediaRecorder's track (from audioDest) never changes.
          micSource.disconnect();
          micStream.getTracks().forEach((t) => t.stop());
          micStream = newStream;
          micSource = audioCtx.createMediaStreamSource(newStream);
          micSource.connect(audioDest);
        } catch (err) {
          console.warn("[Showdesk] Failed to switch mic:", err);
        }
      },
      getCurrentMicId: () => currentMicDeviceId,
      audioEnabled: true,
    });
  } catch {
    // Permission denied
    const panel = document.getElementById("sd-panel");
    if (panel) panel.style.display = "";
  }
}

async function handleVideoCapture(
  store: WidgetStore,
  config: ShowdeskConfig,
  onOpenPanel: () => void,
): Promise<void> {
  if (config.navigationMode === "mpa") {
    return handleVideoCaptureMPA(store, config, onOpenPanel);
  }
  return handleVideoCaptureSPA(store, config, onOpenPanel);
}

/** SPA mode — in-page recording (original behaviour). */
async function handleVideoCaptureSPA(
  store: WidgetStore,
  config: ShowdeskConfig,
  onOpenPanel: () => void,
): Promise<void> {
  try {
    // Hide panel
    const panel = document.getElementById("sd-panel");
    if (panel) panel.style.display = "none";

    const recorder = new ScreenRecorder();
    recorder.onStop = (blob: Blob) => {
      // Restore FAB and re-open panel
      hideRecordingController(onOpenPanel);
      if (panel) panel.style.display = "";
      handleSendAttachment(blob, "video", "recording.webm", store, config);
    };

    await recorder.start({
      mode: "screen",
      audio: true,
      camera: false,
    });

    // Transform FAB into recording controller
    showRecordingController({
      onStop: () => recorder.stop(),
      onToggleAudio: () => recorder.toggleAudio(),
      onSwitchMic: (deviceId) => recorder.switchMicrophone(deviceId),
      getCurrentMicId: () => recorder.micDeviceId ?? "",
      audioEnabled: recorder.isAudioEnabled,
    });
  } catch {
    const panel = document.getElementById("sd-panel");
    if (panel) panel.style.display = "";
  }
}

/* ------------------------------------------------------------------ */
/* MPA popup state — kept at module level so re-attachment works.       */
/* ------------------------------------------------------------------ */
let activePopupHandle: PopupHandle | null = null;

/** MPA mode — open recording in a popup window. */
function handleVideoCaptureMPA(
  store: WidgetStore,
  config: ShowdeskConfig,
  onOpenPanel: () => void,
): void {
  const session = store.state.session;
  if (!session) return;

  const handle = launchRecorderPopup(
    {
      token: config.token,
      apiUrl: config.apiUrl,
      sessionId: session.sessionId,
      ticketId: store.state.activeTicketId,
      color: config.color,
    },
    (msg) => handlePopupMessage(msg, store, config, onOpenPanel),
  );

  if (!handle) {
    // Popup was blocked — fall back to in-page
    console.warn("[Showdesk] Popup blocked — falling back to in-page recording.");
    handleVideoCaptureSPA(store, config, onOpenPanel);
    return;
  }

  activePopupHandle = handle;

  // Hide panel and show a popup-aware recording controller on the FAB
  const panel = document.getElementById("sd-panel");
  if (panel) panel.style.display = "none";

  showPopupRecordingController({
    onStop: () => handle.stop(),
  });
}

function handlePopupMessage(
  msg: RecordingMessage,
  store: WidgetStore,
  config: ShowdeskConfig,
  onOpenPanel: () => void,
): void {
  switch (msg.type) {
    case "recording-started":
      // FAB already shows popup controller — nothing extra
      break;

    case "upload-complete":
      // The popup uploaded directly — refresh the active conversation
      if (msg.ticketId && !store.state.activeTicketId) {
        store.update({ activeTicketId: msg.ticketId });
      }
      cleanupPopup(onOpenPanel);
      break;

    case "upload-failed":
    case "recording-error":
      cleanupPopup(onOpenPanel);
      break;

    case "popup-closed":
      cleanupPopup(onOpenPanel);
      break;

    case "status-response":
      // Re-attachment after navigation — update FAB with elapsed time
      if (msg.isRecording || msg.isUploading) {
        const panel = document.getElementById("sd-panel");
        if (panel) panel.style.display = "none";
        showPopupRecordingController({
          onStop: () => activePopupHandle?.stop(),
          initialElapsed: msg.elapsed,
        });
      }
      break;

    // duration-warning, upload-started, upload-progress, recording-stopped:
    // informational — no action needed on the main page
  }
}

function cleanupPopup(onOpenPanel: () => void): void {
  if (activePopupHandle) {
    activePopupHandle.destroy();
    activePopupHandle = null;
  }
  hideRecordingController(onOpenPanel);
  const panel = document.getElementById("sd-panel");
  if (panel) panel.style.display = "";
}

/**
 * Probe for an existing popup recorder after MPA navigation.
 * Called once on widget init when navigationMode === "mpa".
 */
export async function reattachPopupIfNeeded(
  store: WidgetStore,
  config: ShowdeskConfig,
  onOpenPanel: () => void,
): Promise<void> {
  const handle = await probeExistingPopup((msg) =>
    handlePopupMessage(msg, store, config, onOpenPanel),
  );
  if (handle) {
    activePopupHandle = handle;
  }
}
