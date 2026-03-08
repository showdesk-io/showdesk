/**
 * API functions for custom priority level operations.
 */

import { apiClient } from "./client";
import type { PaginatedResponse } from "@/types";

export interface PriorityLevel {
  id: string;
  organization: string;
  name: string;
  slug: string;
  color: string;
  position: number;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export async function fetchPriorities(): Promise<PriorityLevel[]> {
  const response = await apiClient.get<PaginatedResponse<PriorityLevel>>(
    "/priorities/",
    { params: { page_size: 100 } },
  );
  return response.data.results;
}

export async function createPriority(data: {
  name: string;
  slug: string;
  color: string;
  position: number;
  is_default?: boolean;
}): Promise<PriorityLevel> {
  const response = await apiClient.post<PriorityLevel>("/priorities/", data);
  return response.data;
}

export async function updatePriority(
  id: string,
  data: Partial<{
    name: string;
    slug: string;
    color: string;
    position: number;
    is_default: boolean;
  }>,
): Promise<PriorityLevel> {
  const response = await apiClient.patch<PriorityLevel>(
    `/priorities/${id}/`,
    data,
  );
  return response.data;
}

export async function deletePriority(id: string): Promise<void> {
  await apiClient.delete(`/priorities/${id}/`);
}
