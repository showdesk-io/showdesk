/**
 * Admin endpoints for managing OrgJoinRequest entries.
 */

import { apiClient } from "./client";
import type { OrgJoinRequest, PaginatedResponse } from "@/types";

export async function fetchJoinRequests(
  status: "pending" | "approved" | "rejected" = "pending",
): Promise<OrgJoinRequest[]> {
  const response = await apiClient.get<PaginatedResponse<OrgJoinRequest>>(
    "/join-requests/",
    { params: { status, page_size: 100 } },
  );
  return response.data.results;
}

export async function approveJoinRequest(id: string): Promise<OrgJoinRequest> {
  const response = await apiClient.post<OrgJoinRequest>(
    `/join-requests/${id}/approve/`,
  );
  return response.data;
}

export async function rejectJoinRequest(id: string): Promise<OrgJoinRequest> {
  const response = await apiClient.post<OrgJoinRequest>(
    `/join-requests/${id}/reject/`,
  );
  return response.data;
}
