/**
 * How the detail pages show values that may be absent.
 */

import { format } from "date-fns";

export const NO_VALUE = "—";

export function formatDateTime(value: string | null | undefined): string {
  return value ? format(new Date(value), "MMM d, yyyy HH:mm") : NO_VALUE;
}

/** Cents as a plain amount: the API gives no currency. */
export function formatMrr(cents: number | null | undefined): string {
  return cents === null || cents === undefined ? NO_VALUE : (cents / 100).toFixed(2);
}
