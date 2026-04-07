/**
 * API functions for instance setup.
 */

import { apiClient } from "./client";

export async function fetchSetupStatus(): Promise<{ initialized: boolean }> {
  const response = await apiClient.get<{ initialized: boolean }>(
    "/setup/status/",
  );
  return response.data;
}

export async function initializeInstance(data: {
  email: string;
  first_name: string;
  last_name?: string;
}): Promise<void> {
  await apiClient.post("/setup/initialize/", data);
}
