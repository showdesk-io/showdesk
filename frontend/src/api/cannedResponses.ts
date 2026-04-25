/**
 * API functions for reusable reply templates.
 */

import { apiClient } from "./client";
import type { PaginatedResponse, User } from "@/types";

export interface CannedResponse {
  id: string;
  organization: string;
  created_by: string;
  created_by_detail?: User | null;
  name: string;
  shortcut: string;
  body: string;
  is_shared: boolean;
  position: number;
  usage_count: number;
  created_at: string;
  updated_at: string;
}

export async function fetchCannedResponses(): Promise<CannedResponse[]> {
  const response = await apiClient.get<PaginatedResponse<CannedResponse>>(
    "/canned-responses/",
    { params: { page_size: 200 } },
  );
  return response.data.results;
}

export async function createCannedResponse(data: {
  name: string;
  shortcut?: string;
  body: string;
  is_shared?: boolean;
  position?: number;
}): Promise<CannedResponse> {
  const response = await apiClient.post<CannedResponse>(
    "/canned-responses/",
    data,
  );
  return response.data;
}

export async function updateCannedResponse(
  id: string,
  data: Partial<{
    name: string;
    shortcut: string;
    body: string;
    is_shared: boolean;
    position: number;
  }>,
): Promise<CannedResponse> {
  const response = await apiClient.patch<CannedResponse>(
    `/canned-responses/${id}/`,
    data,
  );
  return response.data;
}

export async function deleteCannedResponse(id: string): Promise<void> {
  await apiClient.delete(`/canned-responses/${id}/`);
}

export async function recordCannedResponseUse(
  id: string,
): Promise<CannedResponse> {
  const response = await apiClient.post<CannedResponse>(
    `/canned-responses/${id}/record-use/`,
  );
  return response.data;
}
