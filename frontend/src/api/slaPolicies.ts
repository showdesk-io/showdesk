/**
 * API functions for SLA policy CRUD.
 */

import { apiClient } from "./client";
import type { PaginatedResponse } from "@/types";

export type SLAPriority = "low" | "medium" | "high" | "urgent";

export interface SLAPolicy {
  id: string;
  organization: string;
  name: string;
  priority: SLAPriority;
  first_response_minutes: number;
  resolution_minutes: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SLAPolicyInput {
  name: string;
  priority: SLAPriority;
  first_response_minutes: number;
  resolution_minutes: number;
  is_active?: boolean;
}

export async function fetchSLAPolicies(): Promise<SLAPolicy[]> {
  const response = await apiClient.get<PaginatedResponse<SLAPolicy>>(
    "/sla-policies/",
    { params: { page_size: 100 } },
  );
  return response.data.results;
}

export async function createSLAPolicy(
  data: SLAPolicyInput,
): Promise<SLAPolicy> {
  const response = await apiClient.post<SLAPolicy>("/sla-policies/", data);
  return response.data;
}

export async function updateSLAPolicy(
  id: string,
  data: Partial<SLAPolicyInput>,
): Promise<SLAPolicy> {
  const response = await apiClient.patch<SLAPolicy>(
    `/sla-policies/${id}/`,
    data,
  );
  return response.data;
}

export async function deleteSLAPolicy(id: string): Promise<void> {
  await apiClient.delete(`/sla-policies/${id}/`);
}
