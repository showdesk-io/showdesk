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
