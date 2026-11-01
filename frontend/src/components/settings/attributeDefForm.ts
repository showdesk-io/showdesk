/**
 * What the custom attributes form checks and works out before asking the API, which has
 * the last word.
 */

import type { AttributeDefType } from "@/types";

export const MAX_ACTIVE_ATTRIBUTES = 50;

const MAX_KEY_LENGTH = 64;
const KEY_PATTERN = /^[a-z][a-z0-9_]{0,63}$/;
const DIGIT_START_PREFIX = "attr_";

export const TYPE_LABELS: Record<AttributeDefType, string> = {
  string: "Text",
  number: "Number",
  boolean: "Yes/No",
  date: "Date",
  enum: "List",
  url: "URL",
};

/** A key for this label, empty if it holds nothing a key can use. */
export function suggestAttributeKey(label: string): string {
  const words = label
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
  const key = /^[0-9]/.test(words) ? `${DIGIT_START_PREFIX}${words}` : words;
  return key.slice(0, MAX_KEY_LENGTH).replace(/_+$/, "");
}

/** Why the API would refuse this key, null if it wouldn't for its form. */
export function validateAttributeKey(key: string): string | null {
  if (!key) return "A key is required.";
  if (!KEY_PATTERN.test(key) || key.includes("__")) {
    return `Use lowercase letters, digits and single underscores, starting with a letter, in at most ${MAX_KEY_LENGTH} characters.`;
  }
  return null;
}

/** The options a comma-separated text gives: trimmed, non-empty, each once. */
export function parseOptions(text: string): string[] {
  const options = text
    .split(",")
    .map((option) => option.trim())
    .filter(Boolean);
  return [...new Set(options)];
}

export function formatOptions(options: string[]): string {
  return options.join(", ");
}
