import { isAxiosError } from "axios";

export const RATE_LIMIT_MESSAGE =
  "Too many attempts. Please wait a while and try again.";

export function isRateLimited(err: unknown): boolean {
  return isAxiosError(err) && err.response?.status === 429;
}
