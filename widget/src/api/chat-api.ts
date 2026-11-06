/**
 * Chat API Client — REST endpoints for widget messaging.
 */

import type {
  ChatAttachment,
  ChatMessage,
  ConversationSummary,
  ShowdeskConfig,
  WidgetSession,
} from "../types";

/** A refusal from the API, whose status says what it means. */
export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

function headers(
  config: ShowdeskConfig,
  sessionId?: string,
): Record<string, string> {
  const h: Record<string, string> = {
    "X-Widget-Token": config.token,
  };
  if (sessionId) {
    h["X-Widget-Session"] = sessionId;
  }
  return h;
}

/** Create a new session or resume an existing one. */
export async function createOrResumeSession(
  config: ShowdeskConfig,
  sessionId?: string | null,
): Promise<WidgetSession> {
  const body: Record<string, unknown> = {};
  if (sessionId) body.session_id = sessionId;
  const userId = String(config.user?.id ?? "");
  if (userId) body.external_user_id = userId;
  if (config.user?.hash) body.user_hash = config.user.hash;
  if (config.user?.name) body.name = config.user.name;
  if (config.user?.email) body.email = config.user.email;
  if (config.user?.emailHash) body.email_hash = config.user.emailHash;
  if (config.user?.traits) body.traits = config.user.traits;
  if (config.company) {
    const { hash, ...company } = config.company;
    body.company = company;
    if (hash) body.company_hash = hash;
  }

  const res = await fetch(`${config.apiUrl}/tickets/widget_session/`, {
    method: "POST",
    headers: { ...headers(config), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) throw new Error(`Session error: ${res.status}`);
  return parseSession(await res.json());
}

/** A session as the API sends it. */
interface SessionData {
  session_id: string;
  name?: string | null;
  email?: string | null;
  external_user_id?: string | null;
  email_proof_offered?: boolean;
}

function parseSession(data: SessionData): WidgetSession {
  return {
    sessionId: data.session_id,
    name: data.name || "",
    email: data.email || "",
    externalUserId: data.external_user_id || "",
    emailProofOffered: data.email_proof_offered === true,
  };
}

/** Update contact info on the session. The session as the backend now has it. */
export async function updateSessionContact(
  config: ShowdeskConfig,
  sessionId: string,
  name: string,
  email: string,
): Promise<WidgetSession> {
  const res = await fetch(`${config.apiUrl}/tickets/widget_session/`, {
    method: "PATCH",
    headers: { ...headers(config, sessionId), "Content-Type": "application/json" },
    body: JSON.stringify({ name, email }),
  });
  if (!res.ok) throw new Error(`Update contact error: ${res.status}`);
  return parseSession(await res.json());
}

/**
 * Ask for a code proving the session's email. The answer is the same whether a code
 * went or not: it only goes when there are conversations to see.
 */
export async function requestEmailCode(
  config: ShowdeskConfig,
  sessionId: string,
): Promise<void> {
  const res = await fetch(`${config.apiUrl}/tickets/widget_email_code/`, {
    method: "POST",
    headers: { ...headers(config, sessionId), "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!res.ok) throw new ApiError(`Email code error: ${res.status}`, res.status);
}

/** Prove the session's email with a code. True if the email is now proven. */
export async function verifyEmailCode(
  config: ShowdeskConfig,
  sessionId: string,
  code: string,
): Promise<boolean> {
  const res = await fetch(`${config.apiUrl}/tickets/widget_email_verify/`, {
    method: "POST",
    headers: { ...headers(config, sessionId), "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  if (!res.ok) throw new ApiError(`Email verify error: ${res.status}`, res.status);
  const data = await res.json();
  return data?.verified === true;
}

/** Send a text message. Returns ticket_id, message_id, reference. */
export async function sendMessage(
  config: ShowdeskConfig,
  sessionId: string,
  ticketId: string | null,
  body: string,
  bodyType: string = "text",
  context?: Record<string, unknown>,
): Promise<{
  ticketId: string;
  messageId: string;
  reference: string;
  createdAt: string;
}> {
  const payload: Record<string, unknown> = { body, body_type: bodyType };
  if (ticketId) payload.ticket_id = ticketId;
  if (context) payload.context = context;

  const res = await fetch(`${config.apiUrl}/tickets/widget_message/`, {
    method: "POST",
    headers: { ...headers(config, sessionId), "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok) throw new ApiError(`Send message error: ${res.status}`, res.status);
  const data = await res.json();
  return {
    ticketId: data.ticket_id,
    messageId: data.message_id,
    reference: data.reference,
    createdAt: data.created_at,
  };
}

/** Upload an attachment (screenshot, audio, video, file) as a message. */
export async function sendAttachmentMessage(
  config: ShowdeskConfig,
  sessionId: string,
  ticketId: string | null,
  file: Blob,
  bodyType: string,
  filename: string,
  extra?: Record<string, string>,
): Promise<{
  ticketId: string;
  messageId: string;
  reference: string;
  createdAt: string;
}> {
  const form = new FormData();
  form.append("file", file, filename);
  form.append("body_type", bodyType);
  if (ticketId) form.append("ticket_id", ticketId);
  if (extra) {
    for (const [k, v] of Object.entries(extra)) {
      form.append(k, v);
    }
  }

  const res = await fetch(
    `${config.apiUrl}/tickets/widget_message_attachment/`,
    {
      method: "POST",
      headers: headers(config, sessionId),
      body: form,
    },
  );

  if (!res.ok) throw new ApiError(`Upload error: ${res.status}`, res.status);
  const data = await res.json();
  return {
    ticketId: data.ticket_id,
    messageId: data.message_id,
    reference: data.reference,
    createdAt: data.created_at,
  };
}

/** Fetch messages for a conversation. */
export async function fetchConversation(
  config: ShowdeskConfig,
  sessionId: string,
  ticketId: string,
): Promise<{
  ticketId: string;
  reference: string;
  status: string;
  /**
   * Not to be written on: seen through the contact's history but not this
   * session's, or closed too long ago to reopen.
   */
  readOnly: boolean;
  /** Closed too long ago to reopen: a message would be refused. */
  closed: boolean;
  messages: ChatMessage[];
}> {
  const res = await fetch(
    `${config.apiUrl}/tickets/widget_conversation/?ticket_id=${ticketId}`,
    { headers: headers(config, sessionId) },
  );

  if (!res.ok) throw new ApiError(`Fetch conversation error: ${res.status}`, res.status);
  const data = await res.json();
  return {
    ticketId: data.ticket_id,
    reference: data.reference,
    status: data.status,
    readOnly: data.read_only === true || data.can_reply === false,
    closed: data.can_reply === false,
    messages: (data.messages || []).map(mapMessage),
  };
}

/** Mark a conversation as read (resets unread_count on the server). */
export async function markConversationRead(
  config: ShowdeskConfig,
  sessionId: string,
  ticketId: string,
): Promise<void> {
  try {
    await fetch(`${config.apiUrl}/tickets/widget_mark_read/`, {
      method: "POST",
      headers: { ...headers(config, sessionId), "Content-Type": "application/json" },
      body: JSON.stringify({ ticket_id: ticketId }),
    });
  } catch {
    // Non-critical: if the network blip loses the mark, user can reopen.
  }
}

/** Fetch conversation history list. */
export async function fetchHistory(
  config: ShowdeskConfig,
  sessionId: string,
): Promise<ConversationSummary[]> {
  const res = await fetch(`${config.apiUrl}/tickets/widget_history/`, {
    headers: headers(config, sessionId),
  });

  if (!res.ok) throw new Error(`Fetch history error: ${res.status}`);
  const data = await res.json();
  return (data || []).map(
    (item: Record<string, unknown>) =>
      ({
        id: item.id,
        reference: item.reference,
        title: item.title,
        status: item.status,
        lastMessagePreview: item.last_message_preview || "",
        lastMessageAt: item.last_message_at || null,
        unreadCount: item.unread_count || 0,
      }) as ConversationSummary,
  );
}

/** Delete a user message. */
export async function deleteMessage(
  config: ShowdeskConfig,
  sessionId: string,
  messageId: string,
): Promise<void> {
  const res = await fetch(
    `${config.apiUrl}/tickets/widget_message_delete/?message_id=${messageId}`,
    {
      method: "DELETE",
      headers: headers(config, sessionId),
    },
  );
  if (!res.ok) throw new Error(`Delete message error: ${res.status}`);
}

/** Files as the API and the WebSocket list them. */
export function mapAttachments(raw: unknown): ChatAttachment[] {
  return ((raw as Array<Record<string, unknown>>) || []).map((a) => ({
    id: a.id as string,
    url: a.file as string,
    filename: a.filename as string,
    contentType: a.content_type as string,
    fileSize: a.file_size as number,
  }));
}

function mapMessage(raw: Record<string, unknown>): ChatMessage {
  return {
    id: raw.id as string,
    ticketId: raw.ticket as string,
    body: (raw.body as string) || "",
    bodyType: (raw.body_type as ChatMessage["bodyType"]) || "text",
    senderType: (raw.sender_type as ChatMessage["senderType"]) || "agent",
    senderName: (raw.sender_name as string) || "",
    attachments: mapAttachments(raw.attachments),
    createdAt: raw.created_at as string,
    ...(typeof raw.deletable === "boolean" ? { deletable: raw.deletable } : {}),
    _status: "sent",
  };
}
