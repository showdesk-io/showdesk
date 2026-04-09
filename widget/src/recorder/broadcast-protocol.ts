/**
 * BroadcastChannel protocol for popup ↔ widget communication.
 *
 * The popup recorder and the main-page widget share a BroadcastChannel
 * on the same origin (the popup is opened as a blob URL, inheriting the
 * client site's origin). Each new page load re-creates its channel and
 * can immediately communicate with the still-alive popup.
 */

export const RECORDING_CHANNEL = "showdesk-recording";

/* ------------------------------------------------------------------ */
/* Messages: popup → widget (main page)                                */
/* ------------------------------------------------------------------ */

export interface RecordingStarted {
  type: "recording-started";
}

export interface RecordingStopped {
  type: "recording-stopped";
  blobSize: number;
}

export interface RecordingError {
  type: "recording-error";
  error: string;
}

export interface UploadStarted {
  type: "upload-started";
}

export interface UploadProgress {
  type: "upload-progress";
  percent: number;
}

export interface UploadComplete {
  type: "upload-complete";
  ticketId: string;
  messageId: string;
}

export interface UploadFailed {
  type: "upload-failed";
  error: string;
}

export interface DurationWarning {
  type: "duration-warning";
  minutes: number;
}

export interface PopupClosed {
  type: "popup-closed";
}

export interface StatusResponse {
  type: "status-response";
  isRecording: boolean;
  elapsed: number;
  isUploading: boolean;
}

/* ------------------------------------------------------------------ */
/* Messages: widget (main page) → popup                                */
/* ------------------------------------------------------------------ */

export interface StopRequested {
  type: "stop-requested";
}

export interface StatusRequest {
  type: "status-request";
}

/* ------------------------------------------------------------------ */
/* Union type                                                          */
/* ------------------------------------------------------------------ */

export type RecordingMessage =
  | RecordingStarted
  | RecordingStopped
  | RecordingError
  | UploadStarted
  | UploadProgress
  | UploadComplete
  | UploadFailed
  | DurationWarning
  | PopupClosed
  | StatusResponse
  | StopRequested
  | StatusRequest;
