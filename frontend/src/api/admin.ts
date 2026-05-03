/**
 * API functions for platform admin operations.
 */

import { apiClient } from "./client";
import type {
  OrganizationStats,
  PaginatedResponse,
  PlatformOrganization,
  PlatformOrganizationDetail,
} from "@/types";

// ── Organizations ─────────────────────────────────────────────────────

export interface FetchOrganizationsParams {
  search?: string;
  page?: number;
  page_size?: number;
}

export async function fetchPlatformOrganizations(
  params?: FetchOrganizationsParams,
): Promise<PaginatedResponse<PlatformOrganization>> {
  const response = await apiClient.get<PaginatedResponse<PlatformOrganization>>(
    "/platform/organizations/",
    { params },
  );
  return response.data;
}

export async function fetchPlatformOrganizationDetail(
  id: string,
): Promise<PlatformOrganizationDetail> {
  const response = await apiClient.get<PlatformOrganizationDetail>(
    `/platform/organizations/${id}/`,
  );
  return response.data;
}

export interface CreateOrganizationData {
  name: string;
  slug: string;
}

export async function createPlatformOrganization(
  data: CreateOrganizationData,
): Promise<PlatformOrganizationDetail> {
  const response = await apiClient.post<PlatformOrganizationDetail>(
    "/platform/organizations/",
    data,
  );
  return response.data;
}

export async function updatePlatformOrganization(
  id: string,
  data: Partial<PlatformOrganizationDetail>,
): Promise<PlatformOrganizationDetail> {
  const response = await apiClient.patch<PlatformOrganizationDetail>(
    `/platform/organizations/${id}/`,
    data,
  );
  return response.data;
}

export async function deletePlatformOrganization(
  id: string,
): Promise<void> {
  await apiClient.delete(`/platform/organizations/${id}/`);
}

export async function suspendPlatformOrganization(
  id: string,
): Promise<PlatformOrganizationDetail> {
  const response = await apiClient.post<PlatformOrganizationDetail>(
    `/platform/organizations/${id}/suspend/`,
  );
  return response.data;
}

export async function fetchOrganizationStats(
  id: string,
): Promise<OrganizationStats> {
  const response = await apiClient.get<OrganizationStats>(
    `/platform/organizations/${id}/stats/`,
  );
  return response.data;
}

// ── Platform-wide usage ──────────────────────────────────────────────

export type UsagePeriod = "all" | "month";

export interface PlatformUsageTotals {
  organizations_total: number;
  organizations_active: number;
  agents_active: number;
  tickets_total: number;
  videos_total: number;
  video_minutes: number;
  attachment_storage_bytes: number;
}

export interface PlatformUsageOrgRow {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
  agents: number;
  tickets: number;
  videos: number;
  video_minutes: number;
  storage_bytes: number;
}

export interface PlatformUsageResponse {
  period: UsagePeriod;
  platform: PlatformUsageTotals;
  organizations: PlatformUsageOrgRow[];
}

export async function fetchPlatformUsage(
  period: UsagePeriod = "all",
): Promise<PlatformUsageResponse> {
  const response = await apiClient.get<PlatformUsageResponse>(
    "/platform/organizations/usage/",
    { params: { period } },
  );
  return response.data;
}
