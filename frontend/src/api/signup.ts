/**
 * Public signup endpoints.
 *
 * No JWT — these are reachable from /signup before the user has any session.
 * Throttled at 5/h/IP on the server, so the form should debounce.
 */

import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api/v1";

const publicClient = axios.create({
  baseURL: API_BASE_URL,
  headers: { "Content-Type": "application/json" },
});

export interface SignupPayload {
  email: string;
  full_name: string;
  org_name?: string;
  org_slug?: string;
}

export interface SignupCreatedResponse {
  status: "created";
  email: string;
  organization: { id: string; slug: string; name: string };
}

export interface SignupJoinRequestedResponse {
  status: "join_requested";
  email: string;
  organization: { name: string };
}

export type SignupResponse =
  | SignupCreatedResponse
  | SignupJoinRequestedResponse;

export async function signup(payload: SignupPayload): Promise<SignupResponse> {
  const response = await publicClient.post<SignupResponse>(
    "/auth/signup/",
    payload,
  );
  return response.data;
}

export interface CheckSlugResponse {
  available: boolean;
  reason?: "taken" | "reserved" | "invalid_format" | "missing_slug";
  suggestion?: string;
}

export async function checkSlug(slug: string): Promise<CheckSlugResponse> {
  const response = await publicClient.get<CheckSlugResponse>(
    "/auth/check-slug/",
    { params: { slug } },
  );
  return response.data;
}

export interface CheckDomainResponse {
  matches_org: boolean;
  org_name?: string;
  domain?: string;
  reason?: "public_domain" | "invalid_email";
}

export async function checkDomain(email: string): Promise<CheckDomainResponse> {
  const response = await publicClient.get<CheckDomainResponse>(
    "/auth/check-domain/",
    { params: { email } },
  );
  return response.data;
}
