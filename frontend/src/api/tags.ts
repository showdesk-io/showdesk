/**
 * API functions for tag operations.
 */

import { apiClient } from "./client";
import type { PaginatedResponse, Tag } from "@/types";

export async function fetchTags(): Promise<Tag[]> {
  const response = await apiClient.get<PaginatedResponse<Tag>>("/tags/", {
    params: { page_size: 200 },
  });
  return response.data.results;
}

export async function createTag(data: {
  name: string;
  color: string;
}): Promise<Tag> {
  const response = await apiClient.post<Tag>("/tags/", data);
  return response.data;
}

export async function updateTag(
  id: string,
  data: { name?: string; color?: string },
): Promise<Tag> {
  const response = await apiClient.patch<Tag>(`/tags/${id}/`, data);
  return response.data;
}

export async function deleteTag(id: string): Promise<void> {
  await apiClient.delete(`/tags/${id}/`);
}

export async function setTicketTags(
  ticketId: string,
  tagIds: string[],
): Promise<void> {
  await apiClient.post(`/tickets/${ticketId}/set_tags/`, {
    tag_ids: tagIds,
  });
}
