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
  widget_secret: string;
  is_active: boolean;
  widget_color: string;
  widget_position: "bottom-right" | "bottom-left";
  widget_greeting: string;
  video_expiration_days: number;
  video_max_duration_seconds: number;
  agent_count: number;
  email_domain: string;
  onboarding_completed_at: string | null;
  onboarding_step: number;
  created_at: string;
  updated_at: string;
}

export type DomainStatus = "pending" | "verified" | "failed";
export type DomainVerificationMethod = "admin_email" | "dns_txt";

export interface OrganizationDomain {
  id: string;
  domain: string;
  is_branding: boolean;
  is_email_routing: boolean;
  status: DomainStatus;
  verification_method: DomainVerificationMethod | null;
  verification_token: string;
  verified_at: string | null;
  last_check_at: string | null;
  txt_record_name: string;
  txt_record_value: string;
  created_at: string;
  updated_at: string;
}

export type JoinRequestStatus = "pending" | "approved" | "rejected";

export interface OrgJoinRequest {
  id: string;
  email: string;
  full_name: string;
  status: JoinRequestStatus;
  created_at: string;
  decided_at: string | null;
  decided_by: string | null;
  decided_by_email: string | null;
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
  organization: string | null;
  role: UserRole;
  avatar: string | null;
  phone: string;
  timezone: string;
  is_available: boolean;
  is_active: boolean;
  is_superuser: boolean;
  date_joined: string;
}

// ---------------------------------------------------------------------------
// Platform Admin
// ---------------------------------------------------------------------------

export interface PlatformOrganization {
  id: string;
  name: string;
  slug: string;
  domain: string;
  is_active: boolean;
  agent_count: number;
  ticket_count: number;
  created_at: string;
  updated_at: string;
}

export interface PlatformOrganizationDetail extends PlatformOrganization {
  logo: string | null;
  api_token: string;
  widget_secret: string;
  widget_color: string;
  widget_position: "bottom-right" | "bottom-left";
  widget_greeting: string;
  video_expiration_days: number;
  video_max_duration_seconds: number;
}

export interface OrganizationStats {
  tickets: {
    total: number;
    open: number;
    in_progress: number;
    waiting: number;
    resolved: number;
    closed: number;
  };
  agents: {
    total: number;
    active: number;
    inactive: number;
  };
  videos: {
    total: number;
  };
  teams: number;
  tags: number;
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
export type IssueType = "bug" | "question" | "suggestion" | "other";

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
export type SenderType = "user" | "agent" | "system";
export type BodyType = "text" | "audio" | "image" | "video" | "screenshot" | "system";

export interface TicketMessage {
  id: string;
  ticket: string;
  author: string | null;
  author_detail: User | null;
  body: string;
  message_type: MessageType;
  sender_type: SenderType;
  body_type: BodyType;
  sender_name: string;
  attachments: TicketAttachment[];
  created_at: string;
  updated_at: string;
}

export interface ConsoleErrorEntry {
  level: "error" | "warning";
  message: string;
  source: string;
  timestamp: string;
}

export interface NetworkErrorEntry {
  method: string;
  url: string;
  status: number;
  duration_ms: number;
  timestamp: string;
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
  issue_type: IssueType;
  external_user_id: string;
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
  context_metadata: {
    language?: string;
    timezone?: string;
    referrer?: string;
    console_errors?: ConsoleErrorEntry[];
    network_errors?: NetworkErrorEntry[];
    [key: string]: unknown;
  };
  sla_policy: string | null;
  first_response_at: string | null;
  resolved_at: string | null;
  closed_at: string | null;
  messages: TicketMessage[];
  videos: VideoRecording[];
  created_at: string;
  updated_at: string;
}

export interface TicketListItem {
  id: string;
  reference: string;
  title: string;
  description: string;
  status: TicketStatus;
  priority: TicketPriority;
  source: TicketSource;
  issue_type: IssueType;
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
// Saved Views
// ---------------------------------------------------------------------------

export interface SavedViewFilters {
  status?: string;
  priority?: string;
  assigned_agent?: string;
  assigned_team?: string;
  tags?: string;
  search?: string;
}

export interface SavedView {
  id: string;
  organization: string;
  created_by: string;
  created_by_detail: User | null;
  name: string;
  filters: SavedViewFilters;
  is_shared: boolean;
  position: number;
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
