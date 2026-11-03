/**
 * The public conversation page's API, reached by a link mailed to a requester.
 *
 * Deliberately not `apiClient`: that one attaches the agent's JWT and sends them to
 * /login on a 401. The link is the only credential here, and an agent logged in on
 * the same browser is no one to this API.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api/v1";

export interface ConversationAttachment {
  id: string;
  filename: string;
  file: string;
  content_type: string;
  file_size: number;
}

export interface ConversationMessage {
  id: string;
  body: string;
  body_type: string;
  sender_type: "user" | "agent" | "system";
  sender_name: string;
  attachments: ConversationAttachment[];
  created_at: string;
}

export interface Conversation {
  organization: { name: string; logo: string; color: string };
  reference: string;
  title: string;
  status: string;
  can_reply: boolean;
  messages: ConversationMessage[];
}

/** A refused request: 404 (no such conversation), 410 (expired link), 400, 429… */
export class ConversationError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(`Conversation request failed with status ${status}`);
    this.name = "ConversationError";
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: "omit",
    headers: { Accept: "application/json", ...init.headers },
  });
  if (!response.ok) {
    throw new ConversationError(response.status);
  }
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

function conversationPath(token: string): string {
  return `/conversations/${encodeURIComponent(token)}/`;
}

export function fetchConversation(token: string): Promise<Conversation> {
  return request<Conversation>(conversationPath(token));
}

export function postConversationMessage(
  token: string,
  body: string,
): Promise<ConversationMessage> {
  return request<ConversationMessage>(`${conversationPath(token)}messages/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body }),
  });
}

export function postConversationAttachment(
  token: string,
  file: File,
): Promise<ConversationMessage> {
  const form = new FormData();
  form.append("file", file);
  return request<ConversationMessage>(`${conversationPath(token)}attachments/`, {
    method: "POST",
    body: form,
  });
}

/** Ask for a fresh link, mailed to the conversation's own address. Always accepted. */
export async function renewConversationLink(token: string): Promise<void> {
  await request<void>("/conversations/renew/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
}
