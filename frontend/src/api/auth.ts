/**
 * API functions for OTP authentication.
 */

import { apiClient } from "./client";
import type { AuthTokens } from "@/types";

/**
 * Request an OTP code to be sent to the given email.
 * Always returns 200 regardless of whether the email exists
 * (to prevent enumeration).
 */
export async function requestOTP(email: string): Promise<void> {
  await apiClient.post("/auth/request-otp/", { email });
}

/**
 * Verify an OTP code and receive JWT tokens.
 */
export async function verifyOTP(
  email: string,
  code: string,
): Promise<AuthTokens> {
  const response = await apiClient.post<AuthTokens>("/auth/verify-otp/", {
    email,
    code,
  });
  return response.data;
}

/**
 * Refresh an expired access token.
 */
export async function refreshToken(refresh: string): Promise<{ access: string }> {
  const response = await apiClient.post<{ access: string }>(
    "/auth/token/refresh/",
    { refresh },
  );
  return response.data;
}
