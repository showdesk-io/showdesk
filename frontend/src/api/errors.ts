/**
 * Reads what the API answers when it refuses a request.
 */

import { isAxiosError } from "axios";

export interface ApiError {
  /** HTTP status, null when no response came back. */
  status: number | null;
  /** An error about no field in particular: `detail` or `non_field_errors`. */
  message: string | null;
  /** Errors by field name. */
  fields: Record<string, string[]>;
  /** Errors by custom attribute key, under `attributes` in the response. */
  attributes: Record<string, string[]>;
}

function isMessages(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function messagesByKey(data: object): Record<string, string[]> {
  return Object.fromEntries(
    Object.entries(data).filter((entry): entry is [string, string[]] =>
      isMessages(entry[1]),
    ),
  );
}

export function parseApiError(error: unknown): ApiError {
  const parsed: ApiError = { status: null, message: null, fields: {}, attributes: {} };
  if (!isAxiosError(error) || !error.response) {
    return parsed;
  }
  parsed.status = error.response.status;
  const data: unknown = error.response.data;
  if (typeof data !== "object" || data === null) {
    return parsed;
  }

  const { detail, non_field_errors, attributes, ...fields } = data as Record<
    string,
    unknown
  >;
  parsed.fields = messagesByKey(fields);
  if (typeof detail === "string") {
    parsed.message = detail;
  } else if (isMessages(non_field_errors)) {
    parsed.message = non_field_errors[0] ?? null;
  }
  if (isMessages(attributes)) {
    parsed.fields.attributes = attributes;
  } else if (typeof attributes === "object" && attributes !== null) {
    parsed.attributes = messagesByKey(attributes);
  }
  return parsed;
}
