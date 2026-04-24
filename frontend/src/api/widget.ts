/**
 * In-app Showdesk widget (dogfooding) — bootstrap API client.
 */

import { apiClient } from "./client";

export interface WidgetIdentity {
  token: string;
  user_hash: string;
  external_user_id: string;
  user: {
    id: string;
    name: string;
    email: string;
  };
}

export async function fetchInternalWidgetIdentity(): Promise<WidgetIdentity> {
  const response = await apiClient.get<WidgetIdentity>("/widget/identity-hash/");
  return response.data;
}
