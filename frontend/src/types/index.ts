/**
 * Core type definitions for the Showdesk frontend.
 */

// ---------------------------------------------------------------------------
// Organizations
// ---------------------------------------------------------------------------

export interface Organization {
  id: string;
  name: string;
  slug: string;
  domain: string;
  logo: string | null;
  api_token: string;
  is_active: boolean;
  widget_color: string;
  widget_position: "bottom-right" | "bottom-left";
  widget_greeting: string;
  video_expiration_days: number;
  video_max_duration_seconds: number;
  agent_count: number;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------

export type UserRole = "admin" | "agent" | "end_user";

export interface User {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  organization: string;
  role: UserRole;
  avatar: string | null;
  phone: string;
  timezone: string;
  is_available: boolean;
  is_active: boolean;
  date_joined: string;
}

// ---------------------------------------------------------------------------
// Teams
// ---------------------------------------------------------------------------

export interface Team {
  id: string;
  organization: string;
  name: string;
  description: string;
  members: User[];
  lead: string | null;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Tickets
// ---------------------------------------------------------------------------

export type TicketStatus =
  | "open"
  | "in_progress"
  | "waiting"
  | "resolved"
  | "closed";

export type TicketPriority = "low" | "medium" | "high" | "urgent";

export type TicketSource = "widget" | "email" | "api" | "agent";

export interface Tag {
  id: string;
  organization: string;
  name: string;
  color: string;
  created_at: string;
}

export interface TicketAttachment {
  id: string;
  ticket: string;
  message: string | null;
  uploaded_by: string | null;
  file: string;
  filename: string;
  content_type: string;
  file_size: number;
  created_at: string;
}

export type MessageType = "reply" | "internal_note";

export interface TicketMessage {
  id: string;
  ticket: string;
  author: string | null;
  author_detail: User | null;
  body: string;
  message_type: MessageType;
  attachments: TicketAttachment[];
  created_at: string;
  updated_at: string;
}

export interface Ticket {
  id: string;
  organization: string;
  reference: string;
  title: string;
  description: string;
  status: TicketStatus;
  priority: TicketPriority;
  source: TicketSource;
  requester: string | null;
  requester_detail: User | null;
  requester_name: string;
  requester_email: string;
  assigned_agent: string | null;
  assigned_agent_detail: User | null;
  assigned_team: string | null;
  tags_detail: Tag[];
  context_url: string;
  context_user_agent: string;
  context_os: string;
  context_browser: string;
  context_screen_resolution: string;
  context_metadata: Record<string, unknown>;
  sla_policy: string | null;
  first_response_at: string | null;
  resolved_at: string | null;
  closed_at: string | null;
  messages: TicketMessage[];
  created_at: string;
  updated_at: string;
}

export interface TicketListItem {
  id: string;
  reference: string;
  title: string;
  status: TicketStatus;
  priority: TicketPriority;
  source: TicketSource;
  requester_detail: User | null;
  requester_name: string;
  requester_email: string;
  assigned_agent_detail: User | null;
  assigned_team: string | null;
  tags_detail: Tag[];
  message_count: number;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Videos
// ---------------------------------------------------------------------------

export type VideoStatus =
  | "uploading"
  | "processing"
  | "ready"
  | "failed"
  | "expired";

export type RecordingType = "screen" | "screen_camera" | "camera";

export interface VideoRecording {
  id: string;
  ticket: string;
  recorded_by: string | null;
  original_file: string;
  processed_file: string;
  thumbnail: string;
  status: VideoStatus;
  recording_type: RecordingType;
  duration_seconds: number | null;
  file_size: number | null;
  width: number | null;
  height: number | null;
  mime_type: string;
  has_audio: boolean;
  has_camera: boolean;
  transcription: string;
  transcription_status: string;
  transcription_language: string;
  expires_at: string | null;
  is_redacted: boolean;
  is_playable: boolean;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface AuthTokens {
  access: string;
  refresh: string;
}
