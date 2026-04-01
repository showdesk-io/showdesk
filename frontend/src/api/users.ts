/**
 * API functions for user, team, and organization operations.
 */

import { apiClient } from "./client";
import type { Organization, PaginatedResponse, Team, User } from "@/types";

// ── Users ──────────────────────────────────────────────────────────────

export async function fetchCurrentUser(): Promise<User> {
  const response = await apiClient.get<User>("/users/me/");
  return response.data;
}

export async function fetchAgents(): Promise<User[]> {
  const response = await apiClient.get<PaginatedResponse<User>>("/users/", {
    params: { role: "agent", page_size: 100 },
  });
  return response.data.results;
}

export async function fetchAllUsers(): Promise<User[]> {
  const response = await apiClient.get<PaginatedResponse<User>>("/users/", {
    params: { page_size: 200 },
  });
  return response.data.results;
}

export interface InviteAgentData {
  email: string;
  first_name?: string;
  last_name?: string;
  role?: "admin" | "agent";
}

export async function inviteAgent(data: InviteAgentData): Promise<User> {
  const response = await apiClient.post<User>("/users/invite/", data);
  return response.data;
}

export async function updateUser(
  id: string,
  data: Partial<User>,
): Promise<User> {
  const response = await apiClient.patch<User>(`/users/${id}/`, data);
  return response.data;
}

export async function toggleUserActive(id: string): Promise<User> {
  const response = await apiClient.post<User>(`/users/${id}/toggle_active/`);
  return response.data;
}

// ── Teams ──────────────────────────────────────────────────────────────

export async function fetchTeams(): Promise<Team[]> {
  const response = await apiClient.get<PaginatedResponse<Team>>("/teams/");
  return response.data.results;
}

export async function createTeam(data: {
  name: string;
  description?: string;
  member_ids?: string[];
  lead?: string | null;
}): Promise<Team> {
  const response = await apiClient.post<Team>("/teams/", data);
  return response.data;
}

export async function updateTeam(
  id: string,
  data: Partial<Team & { member_ids?: string[] }>,
): Promise<Team> {
  const response = await apiClient.patch<Team>(`/teams/${id}/`, data);
  return response.data;
}

export async function deleteTeam(id: string): Promise<void> {
  await apiClient.delete(`/teams/${id}/`);
}

// ── Organizations ──────────────────────────────────────────────────────

export async function fetchOrganization(): Promise<Organization> {
  const response = await apiClient.get<PaginatedResponse<Organization>>(
    "/organizations/",
  );
  const org = response.data.results[0];
  if (!org) throw new Error("No organization found");
  return org;
}

export async function updateOrganization(
  id: string,
  data: Partial<Organization>,
): Promise<Organization> {
  const response = await apiClient.patch<Organization>(
    `/organizations/${id}/`,
    data,
  );
  return response.data;
}

export async function regenerateApiToken(orgId: string): Promise<Organization> {
  const response = await apiClient.post<Organization>(
    `/organizations/${orgId}/regenerate_token/`,
  );
  return response.data;
}

// ── Stats ──────────────────────────────────────────────────────────────

export interface TicketStats {
  open: number;
  in_progress: number;
  resolved_today: number;
  urgent: number;
  total: number;
}

export async function fetchTicketStats(): Promise<TicketStats> {
  const [openRes, progressRes, urgentRes, totalRes] = await Promise.all([
    apiClient.get<PaginatedResponse<unknown>>("/tickets/", {
      params: { status: "open", page_size: 1 },
    }),
    apiClient.get<PaginatedResponse<unknown>>("/tickets/", {
      params: { status: "in_progress", page_size: 1 },
    }),
    apiClient.get<PaginatedResponse<unknown>>("/tickets/", {
      params: { priority: "urgent", page_size: 1 },
    }),
    apiClient.get<PaginatedResponse<unknown>>("/tickets/", {
      params: { page_size: 1 },
    }),
  ]);

  return {
    open: openRes.data.count,
    in_progress: progressRes.data.count,
    resolved_today: 0,
    urgent: urgentRes.data.count,
    total: totalRes.data.count,
  };
}
