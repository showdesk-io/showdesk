/**
 * API functions for saved view operations.
 */

import { apiClient } from "./client";
import type { PaginatedResponse, SavedView, SavedViewFilters } from "@/types";

export async function fetchSavedViews(): Promise<SavedView[]> {
  const response = await apiClient.get<PaginatedResponse<SavedView>>(
    "/saved-views/",
    { params: { page_size: 100 } },
  );
  return response.data.results;
}

export async function createSavedView(data: {
  name: string;
  filters: SavedViewFilters;
  is_shared: boolean;
  position?: number;
}): Promise<SavedView> {
  const response = await apiClient.post<SavedView>("/saved-views/", data);
  return response.data;
}

export async function updateSavedView(
  id: string,
  data: Partial<{ name: string; filters: SavedViewFilters; is_shared: boolean; position: number }>,
): Promise<SavedView> {
  const response = await apiClient.patch<SavedView>(`/saved-views/${id}/`, data);
  return response.data;
}

export async function deleteSavedView(id: string): Promise<void> {
  await apiClient.delete(`/saved-views/${id}/`);
}
