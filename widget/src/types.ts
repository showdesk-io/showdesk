/**
 * Type definitions for the Showdesk widget.
 */

import type { ConsoleEntry } from "./collectors/console-collector";
import type { NetworkEntry } from "./collectors/network-collector";

export interface ShowdeskUserIdentity {
  id?: string;
  name?: string;
  email?: string;
}

export interface ShowdeskConfig {
  /** Organization API token for authentication. */
  token: string;
  /** Base URL for the Showdesk API. */
  apiUrl: string;
  /** Position of the floating button. */
  position: "bottom-right" | "bottom-left";
  /** Primary color (hex). */
  color: string;
  /** Button label text. */
  label: string;
  /** Greeting message in the modal header. */
  greeting: string;
  /** Hide the default floating button (for programmatic use). */
  hideButton: boolean;
  /** Optional user identity for pre-filling contact fields and tracking. */
  user?: ShowdeskUserIdentity;
}

export interface TechnicalContext {
  url: string;
  userAgent: string;
  os: string;
  browser: string;
  screenResolution: string;
  language: string;
  timezone: string;
  referrer: string;
  consoleErrors: ConsoleEntry[];
  networkErrors: NetworkEntry[];
}

export interface TicketSubmission {
  title: string;
  description: string;
  requester_name: string;
  requester_email: string;
  priority: string;
  issue_type: string;
  context_url: string;
  context_user_agent: string;
  context_os: string;
  context_browser: string;
  context_screen_resolution: string;
  context_metadata: Record<string, unknown>;
  external_user_id?: string;
}

export interface RecorderState {
  isRecording: boolean;
  isPaused: boolean;
  duration: number;
  hasAudio: boolean;
  hasCamera: boolean;
  blob: Blob | null;
}
