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
  hideRecordingController,
} from "../button";
import { renderContactNudge } from "./contact-nudge";
import { renderMessageBubble } from "./message-bubble";
import { renderMessageInput } from "./message-input";
import { ScreenRecorder } from "../../recorder/screen-recorder";

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
    const micStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
    });

    const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : "audio/webm";

    const chunks: Blob[] = [];
    const recorder = new MediaRecorder(micStream, { mimeType });

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.push(e.data);
    };

    recorder.onstop = () => {
      micStream.getTracks().forEach((t) => t.stop());
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
        const track = micStream.getAudioTracks()[0];
        if (track) {
          track.enabled = !track.enabled;
          return track.enabled;
        }
        return false;
      },
      onSwitchMic: async (deviceId) => {
        // For audio-only, we need to stop and restart with new device
        // since there's no AudioContext routing here
        try {
          const newStream = await navigator.mediaDevices.getUserMedia({
            audio: {
              deviceId: { exact: deviceId },
              echoCancellation: true,
              noiseSuppression: true,
            },
          });
          // Replace track in micStream
          const oldTrack = micStream.getAudioTracks()[0];
          if (oldTrack) {
            micStream.removeTrack(oldTrack);
            oldTrack.stop();
          }
          const newTrack = newStream.getAudioTracks()[0];
          if (newTrack) {
            micStream.addTrack(newTrack);
          }
        } catch (err) {
          console.warn("[Showdesk] Failed to switch mic:", err);
        }
      },
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
      audioEnabled: recorder.isAudioEnabled,
    });
  } catch {
    const panel = document.getElementById("sd-panel");
    if (panel) panel.style.display = "";
  }
}
