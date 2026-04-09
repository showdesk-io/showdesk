/**
 * Popup Launcher — Opens the recording popup and manages communication.
 *
 * Opens a blob-URL popup (same-origin as the client site) that runs a
 * self-contained recorder. Communication uses BroadcastChannel so it
 * survives page navigations on MPA sites.
 *
 * Also provides `probeExistingPopup()` to re-attach to a popup that
 * was started on a previous page (MPA navigation scenario).
 */

import {
  RECORDING_CHANNEL,
  type RecordingMessage,
} from "./broadcast-protocol";
import { buildPopupHtml, type PopupConfig, type PopupRecordingMode } from "./popup-html";

export interface PopupLaunchOptions {
  token: string;
  apiUrl: string;
  sessionId: string;
  ticketId: string | null;
  color: string;
  mode: PopupRecordingMode;
}

export type PopupMessageHandler = (msg: RecordingMessage) => void;

export interface PopupHandle {
  /** Send a stop-requested message to the popup. */
  stop: () => void;
  /** Close the channel and clean up. */
  destroy: () => void;
}

/**
 * Launch the recording popup.
 *
 * MUST be called synchronously from a user gesture (click handler)
 * to avoid popup blockers.
 *
 * Returns null if the popup was blocked.
 */
export function launchRecorderPopup(
  options: PopupLaunchOptions,
  onMessage: PopupMessageHandler,
): PopupHandle | null {
  const cfg: PopupConfig = {
    token: options.token,
    apiUrl: options.apiUrl,
    sessionId: options.sessionId,
    ticketId: options.ticketId,
    color: options.color,
    mode: options.mode,
  };

  const html = buildPopupHtml(cfg);
  const blob = new Blob([html], { type: "text/html" });
  const url = URL.createObjectURL(blob);

  const popup = window.open(
    url,
    "showdesk-recorder",
    "popup,width=380,height=280",
  );

  if (!popup) {
    URL.revokeObjectURL(url);
    return null;
  }

  // Revoke the blob URL after the popup has loaded its content.
  // Revoking too early causes a blank page in some browsers.
  // Use a timeout as a safe fallback in case the load event doesn't fire.
  const revoke = () => { try { URL.revokeObjectURL(url); } catch {} };
  try { popup.addEventListener("load", revoke); } catch { /* cross-origin guard */ }
  setTimeout(revoke, 5000);

  const channel = new BroadcastChannel(RECORDING_CHANNEL);

  channel.onmessage = (event: MessageEvent<RecordingMessage>) => {
    onMessage(event.data);
  };

  return {
    stop() {
      channel.postMessage({ type: "stop-requested" });
    },
    destroy() {
      channel.close();
    },
  };
}

/**
 * Probe for an existing recording popup (after MPA navigation).
 *
 * Opens a BroadcastChannel, sends a status-request, and waits briefly
 * for a status-response. If one arrives, a popup is alive and the
 * handle is returned. Otherwise returns null.
 */
export function probeExistingPopup(
  onMessage: PopupMessageHandler,
  timeoutMs = 500,
): Promise<PopupHandle | null> {
  return new Promise((resolve) => {
    const channel = new BroadcastChannel(RECORDING_CHANNEL);
    let resolved = false;

    channel.onmessage = (event: MessageEvent<RecordingMessage>) => {
      const msg = event.data;
      if (!resolved && msg.type === "status-response") {
        resolved = true;
        // Re-wire to the caller's handler going forward
        channel.onmessage = (e: MessageEvent<RecordingMessage>) => {
          onMessage(e.data);
        };
        // Deliver this first status-response too
        onMessage(msg);
        resolve({
          stop() {
            channel.postMessage({ type: "stop-requested" });
          },
          destroy() {
            channel.close();
          },
        });
      }
    };

    channel.postMessage({ type: "status-request" });

    setTimeout(() => {
      if (!resolved) {
        resolved = true;
        channel.close();
        resolve(null);
      }
    }, timeoutMs);
  });
}
