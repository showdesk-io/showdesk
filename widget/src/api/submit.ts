/**
 * API client for submitting tickets and uploading videos from the widget.
 *
 * All requests authenticate via the organization's API token
 * passed in the X-Widget-Token header. No user account required.
 */

import type { ShowdeskConfig, TicketSubmission } from "../types";

interface TicketResponse {
  id: string;
  reference: string;
}

/**
 * Submit a ticket to the Showdesk API.
 */
export async function submitTicket(
  config: ShowdeskConfig,
  data: TicketSubmission,
): Promise<TicketResponse> {
  const response = await fetch(`${config.apiUrl}/tickets/widget_submit/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Widget-Token": config.token,
    },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Failed to submit ticket: ${response.status} ${errorText}`);
  }

  return response.json() as Promise<TicketResponse>;
}

/**
 * Upload a video recording for a ticket.
 *
 * Uses XMLHttpRequest instead of fetch to support upload progress
 * tracking, giving users visual feedback during large uploads.
 */
export async function uploadVideo(
  config: ShowdeskConfig,
  ticketId: string,
  blob: Blob,
  options: {
    hasAudio: boolean;
    hasCamera: boolean;
    onProgress?: (percent: number) => void;
  },
): Promise<void> {
  const formData = new FormData();
  formData.append("ticket", ticketId);
  formData.append("original_file", blob, `recording-${Date.now()}.webm`);
  formData.append("recording_type", options.hasCamera ? "screen_camera" : "screen");
  formData.append("has_audio", String(options.hasAudio));
  formData.append("has_camera", String(options.hasCamera));
  formData.append("mime_type", blob.type || "video/webm");

  return new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${config.apiUrl}/videos/widget_upload/`);
    xhr.setRequestHeader("X-Widget-Token", config.token);

    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable && options.onProgress) {
        const percent = (e.loaded / e.total) * 100;
        options.onProgress(percent);
      }
    });

    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        reject(new Error(`Failed to upload video: ${xhr.status} ${xhr.responseText}`));
      }
    });

    xhr.addEventListener("error", () => {
      reject(new Error("Network error during video upload."));
    });

    xhr.addEventListener("timeout", () => {
      reject(new Error("Video upload timed out."));
    });

    // 10 minute timeout for large videos
    xhr.timeout = 600000;

    xhr.send(formData);
  });
}
