/**
 * Substitution helpers for canned-response template variables.
 *
 * Templates may include `{{variable}}` placeholders. They are expanded
 * client-side at insertion time using context drawn from the current
 * ticket and the active agent. Unknown placeholders are left intact so
 * authors can spot typos in their templates.
 */

import type { Ticket, User } from "@/types";

export interface CannedResponseContext {
  ticket?: Ticket | null;
  agent?: User | null;
}

const fullName = (
  user: { first_name?: string; last_name?: string } | null | undefined,
): string => {
  if (!user) return "";
  const parts = [user.first_name, user.last_name].filter(Boolean);
  return parts.join(" ").trim();
};

export function buildVariableMap(
  ctx: CannedResponseContext,
): Record<string, string> {
  const { ticket, agent } = ctx;
  const requesterName =
    fullName(ticket?.requester_detail) || ticket?.requester_name || "";
  const requesterEmail =
    ticket?.requester_detail?.email || ticket?.requester_email || "";
  const agentName =
    fullName(agent) ||
    fullName(ticket?.assigned_agent_detail) ||
    agent?.email ||
    "";
  return {
    requester_name: requesterName,
    requester_email: requesterEmail,
    requester_first_name: ticket?.requester_detail?.first_name || "",
    agent_name: agentName,
    ticket_reference: ticket?.reference || "",
    ticket_title: ticket?.title || "",
    ticket_status: ticket?.status || "",
    ticket_priority: ticket?.priority || "",
  };
}

const PLACEHOLDER_RE = /\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}/g;

export function applyTemplateVariables(
  body: string,
  ctx: CannedResponseContext,
): string {
  const vars = buildVariableMap(ctx);
  return body.replace(PLACEHOLDER_RE, (full, key: string) => {
    const value = vars[key];
    return value !== undefined && value !== "" ? value : full;
  });
}

export const AVAILABLE_VARIABLES: Array<{
  key: string;
  description: string;
}> = [
  { key: "requester_name", description: "Requester full name" },
  { key: "requester_first_name", description: "Requester first name" },
  { key: "requester_email", description: "Requester email" },
  { key: "agent_name", description: "Your name" },
  { key: "ticket_reference", description: "Ticket reference (e.g. SD-1234)" },
  { key: "ticket_title", description: "Ticket title" },
  { key: "ticket_status", description: "Ticket status" },
  { key: "ticket_priority", description: "Ticket priority" },
];
