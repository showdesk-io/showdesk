/**
 * Type definitions for the Showdesk widget.
 */

import type { ConsoleEntry } from "./collectors/console-collector";
import type { NetworkEntry } from "./collectors/network-collector";

export interface ShowdeskUserIdentity {
  /** A number is accepted, and signed as its decimal string. */
  id?: string | number;
  name?: string;
  email?: string;
  /**
   * HMAC-SHA256(widget_secret, id) — computed on the host's server, identifies the
   * user and enables ticket history.
   */
  hash?: string;
  /** HMAC-SHA256(widget_secret, "email:" + lowercase email) — optional, proves the email. */
  emailHash?: string;
  /** Custom contact attributes (defined in Settings → Contact attributes). */
  traits?: Record<string, unknown>;
}

export interface ShowdeskCompany {
  /** A number is accepted, and signed as its decimal string. */
  id: string | number;
  name: string;
  domain?: string;
  /** Not signed. Only applied when the payload creates the company. */
  traits?: Record<string, unknown>;
  /**
   * HMAC-SHA256(widget_secret, "company\n" + id + "\n" + name + "\n" + lowercase domain),
   * with domain empty if absent — optional, lets the payload update the company's
   * name and domain and move the contact to it. Doesn't cover traits.
   */
  hash?: string;
}

/** Navigation mode: 'spa' keeps recording in-page, 'mpa' uses a popup that survives navigation. */
export type NavigationMode = "spa" | "mpa";

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
  /** Optional company of the user. Only honoured for HMAC-identified users. */
  company?: ShowdeskCompany;
  /** Navigation mode: 'spa' (default) for single-page apps, 'mpa' for multi-page sites. */
  navigationMode: NavigationMode;
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

/* ------------------------------------------------------------------ */
/* Chat / messaging types                                              */
/* ------------------------------------------------------------------ */

export type WidgetTab = "chat" | "history";

export interface WidgetSession {
  sessionId: string;
  name: string;
  email: string;
  externalUserId: string;
}

export interface ChatAttachment {
  id: string;
  url: string;
  filename: string;
  contentType: string;
  fileSize: number;
}

export type BodyType =
  | "text"
  | "audio"
  | "image"
  | "video"
  | "screenshot"
  | "file"
  | "system";

export type SenderType = "user" | "agent" | "system";

export interface ChatMessage {
  id: string;
  ticketId: string;
  body: string;
  bodyType: BodyType;
  senderType: SenderType;
  senderName: string;
  attachments: ChatAttachment[];
  createdAt: string;
  /** Client-only status for optimistic updates. */
  _status?: "sending" | "sent" | "failed";
  /** Client-only blob URL for immediate preview before server upload. */
  _localUrl?: string;
}

export interface ConversationSummary {
  id: string;
  reference: string;
  title: string;
  status: string;
  lastMessagePreview: string;
  lastMessageAt: string | null;
  unreadCount: number;
}
