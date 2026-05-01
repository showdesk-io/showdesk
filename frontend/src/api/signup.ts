/**
 * Public signup endpoints (OTP-first flow).
 *
 * Steps 1-2 are unauthenticated; steps 3a/3b run authenticated, after
 * /signup/verify-otp/ has issued JWT tokens.
 */

import axios from "axios";
import { apiClient } from "./client";
import type { AuthTokens, User } from "@/types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api/v1";

const publicClient = axios.create({
  baseURL: API_BASE_URL,
  headers: { "Content-Type": "application/json" },
});

// ---------------------------------------------------------------------------
// Step 1: request OTP
// ---------------------------------------------------------------------------

export interface SignupRequestOTPPayload {
  email: string;
  full_name?: string;
}

export async function signupRequestOTP(
  payload: SignupRequestOTPPayload,
): Promise<void> {
  await publicClient.post("/auth/signup/request-otp/", payload);
}

// ---------------------------------------------------------------------------
// Step 2: verify OTP
// ---------------------------------------------------------------------------

export type SignupNextStep = "has_org" | "join_request" | "create_org";

export interface SignupVerifyOTPResponse extends AuthTokens {
  user: User;
  next_step: SignupNextStep;
  domain?: string;
  org_id?: string;
  org_slug?: string;
  org_name?: string;
}

export async function signupVerifyOTP(
  email: string,
  code: string,
): Promise<SignupVerifyOTPResponse> {
  const response = await publicClient.post<SignupVerifyOTPResponse>(
    "/auth/signup/verify-otp/",
    { email, code },
  );
  return response.data;
}

// ---------------------------------------------------------------------------
// Resume helper: where in the wizard should this user be?
// ---------------------------------------------------------------------------

export interface SignupStateResponse {
  user: User;
  next_step: SignupNextStep;
  domain?: string;
  org_id?: string;
  org_slug?: string;
  org_name?: string;
}

export async function fetchSignupState(): Promise<SignupStateResponse> {
  const response = await apiClient.get<SignupStateResponse>(
    "/auth/signup/state/",
  );
  return response.data;
}

// ---------------------------------------------------------------------------
// Step 3a: create org via wizard (authenticated)
// ---------------------------------------------------------------------------

export interface SignupCreateOrgPayload {
  org_name: string;
  org_slug: string;
}

export interface SignupCreateOrgResponse {
  user: User;
  organization: { id: string; slug: string; name: string };
}

export async function signupCreateOrg(
  payload: SignupCreateOrgPayload,
): Promise<SignupCreateOrgResponse> {
  const response = await apiClient.post<SignupCreateOrgResponse>(
    "/auth/signup/create-org/",
    payload,
  );
  return response.data;
}

// ---------------------------------------------------------------------------
// Step 3b: request to join an existing org (authenticated)
// ---------------------------------------------------------------------------

export interface SignupRequestJoinPayload {
  full_name?: string;
}

export interface SignupRequestJoinResponse {
  status: "join_requested";
  organization: { id: string; name: string };
}

export async function signupRequestJoin(
  payload: SignupRequestJoinPayload = {},
): Promise<SignupRequestJoinResponse> {
  const response = await apiClient.post<SignupRequestJoinResponse>(
    "/auth/signup/request-join/",
    payload,
  );
  return response.data;
}

// ---------------------------------------------------------------------------
// Live form helpers (unchanged)
// ---------------------------------------------------------------------------

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
