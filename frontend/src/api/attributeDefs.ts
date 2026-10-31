/**
 * API functions for custom attribute definitions, archived rather than deleted.
 * Agents read them, admins write them.
 */

import { apiClient } from "./client";
import type { AttributeDef, AttributeDefEntity } from "@/types";

const ENDPOINTS: Record<AttributeDefEntity, string> = {
  contact: "/contact-attributes/",
  company: "/company-attributes/",
};

export type AttributeDefCreate = Pick<AttributeDef, "key" | "label" | "type"> &
  Partial<Pick<AttributeDef, "description" | "options" | "is_archived" | "position">>;

/** `key` and `type` can't change. */
export type AttributeDefUpdate = Partial<
  Pick<AttributeDef, "label" | "description" | "options" | "is_archived" | "position">
>;

export async function fetchAttributeDefs(
  entity: AttributeDefEntity,
): Promise<AttributeDef[]> {
  const response = await apiClient.get<AttributeDef[]>(ENDPOINTS[entity]);
  return response.data;
}

export async function createAttributeDef(
  entity: AttributeDefEntity,
  data: AttributeDefCreate,
): Promise<AttributeDef> {
  const response = await apiClient.post<AttributeDef>(ENDPOINTS[entity], data);
  return response.data;
}

export async function updateAttributeDef(
  entity: AttributeDefEntity,
  id: string,
  data: AttributeDefUpdate,
): Promise<AttributeDef> {
  const response = await apiClient.patch<AttributeDef>(
    `${ENDPOINTS[entity]}${id}/`,
    data,
  );
  return response.data;
}
