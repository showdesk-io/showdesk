/**
 * Sorts what the API answers to a refused form between its fields and the form itself.
 */

import { parseApiError } from "@/api/errors";

export interface FormErrors {
  fields: Record<string, string[]>;
  /** About no field, or about one the form doesn't have. */
  general: string[];
}

export const NO_ERRORS: FormErrors = { fields: {}, general: [] };

/** Null when the API said nothing a form could show. */
export function readFormErrors(
  error: unknown,
  formFields: readonly string[],
): FormErrors | null {
  const { message, fields, attributes } = parseApiError(error);
  const known = Object.entries(fields).filter(([key]) => formFields.includes(key));
  const others = Object.entries(fields).filter(([key]) => !formFields.includes(key));
  const general = [
    ...(message ? [message] : []),
    ...others.flatMap(([, messages]) => messages),
    ...Object.values(attributes).flat(),
  ];
  if (known.length === 0 && general.length === 0) return null;
  return { fields: Object.fromEntries(known), general };
}

const SAVE_FAILED = ["Could not save this change."];

/** What to show next to a field whose save was refused, sent alone. */
export function fieldErrors(error: unknown, field: string): string[] {
  const { message, fields } = parseApiError(error);
  const own = fields[field];
  if (own?.length) return own;
  const others = [...(message ? [message] : []), ...Object.values(fields).flat()];
  return others.length > 0 ? others : SAVE_FAILED;
}

/** What to show next to a custom attribute whose save was refused, sent alone. */
export function attributeErrors(error: unknown, key: string): string[] {
  const { attributes } = parseApiError(error);
  return attributes[key]?.length ? attributes[key] : fieldErrors(error, "attributes");
}
