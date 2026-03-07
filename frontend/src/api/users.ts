/**
 * API functions for user and team operations.
 */

import { apiClient } from "./client";
import type { PaginatedResponse, Team, User } from "@/types";

export async function fetchCurrentUser(): Promise<User> {
  const response = await apiClient.get<PaginatedResponse<User>>("/users/", {
    params: { page_size: 1 },
  });
  // The current user is the first result when filtered by auth
  const user = response.data.results[0];
  if (!user) {
    throw new Error("Could not fetch current user.");
  }
  return user;
}

export async function fetchAgents(): Promise<User[]> {
  const response = await apiClient.get<PaginatedResponse<User>>("/users/", {
    params: { role: "agent", page_size: 100 },
  });
  return response.data.results;
}

export async function fetchTeams(): Promise<Team[]> {
  const response = await apiClient.get<PaginatedResponse<Team>>("/teams/");
  return response.data.results;
}

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
    resolved_today: 0, // Requires backend filter by date
    urgent: urgentRes.data.count,
    total: totalRes.data.count,
  };
}
