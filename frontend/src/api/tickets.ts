/**
 * API functions for ticket-related operations.
 */

import { apiClient } from "./client";
import type {
  PaginatedResponse,
  Ticket,
  TicketListItem,
  TicketMessage,
} from "@/types";

export interface TicketFilters {
  status?: string;
  priority?: string;
  assigned_agent?: string;
  tags?: string;
  search?: string;
  page?: number;
}

export async function fetchTickets(
  filters: TicketFilters = {},
): Promise<PaginatedResponse<TicketListItem>> {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      params.append(key, String(value));
    }
  });
  const response = await apiClient.get<PaginatedResponse<TicketListItem>>(
    `/tickets/?${params.toString()}`,
  );
  return response.data;
}

export async function fetchTicket(id: string): Promise<Ticket> {
  const response = await apiClient.get<Ticket>(`/tickets/${id}/`);
  return response.data;
}

export interface CreateTicketData {
  title: string;
  description?: string;
  priority?: string;
  assigned_agent?: string | null;
  assigned_team?: string | null;
  requester_name?: string;
  requester_email?: string;
}

export async function createTicket(data: CreateTicketData): Promise<Ticket> {
  const response = await apiClient.post<Ticket>("/tickets/", data);
  return response.data;
}

export async function updateTicket(
  ticketId: string,
  data: Partial<CreateTicketData>,
): Promise<Ticket> {
  const response = await apiClient.patch<Ticket>(`/tickets/${ticketId}/`, data);
  return response.data;
}

export async function createMessage(
  ticketId: string,
  data: { body: string; message_type: string },
): Promise<TicketMessage> {
  const response = await apiClient.post<TicketMessage>("/messages/", {
    ticket: ticketId,
    ...data,
  });
  return response.data;
}

export async function assignTicket(
  ticketId: string,
  data: { agent_id?: string; team_id?: string },
): Promise<Ticket> {
  const response = await apiClient.post<Ticket>(
    `/tickets/${ticketId}/assign/`,
    data,
  );
  return response.data;
}

export async function resolveTicket(ticketId: string): Promise<Ticket> {
  const response = await apiClient.post<Ticket>(
    `/tickets/${ticketId}/resolve/`,
  );
  return response.data;
}

export async function closeTicket(ticketId: string): Promise<Ticket> {
  const response = await apiClient.post<Ticket>(
    `/tickets/${ticketId}/close/`,
  );
  return response.data;
}

export async function reopenTicket(ticketId: string): Promise<Ticket> {
  const response = await apiClient.post<Ticket>(
    `/tickets/${ticketId}/reopen/`,
  );
  return response.data;
}
