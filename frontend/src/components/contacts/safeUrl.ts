/**
 * Reads a URL someone else provided: a host app, a widget visitor or an import.
 */

const SAFE_PROTOCOLS = ["http:", "https:"];

/**
 * Return `url` as the browser will read it if it's absolute http(s), else null. Never put
 * such a URL in an `href` or a `src` without this: `javascript:` would run in the app.
 */
export function safeHttpUrl(url: unknown): string | null {
  if (typeof url !== "string") return null;
  try {
    const parsed = new URL(url);
    return SAFE_PROTOCOLS.includes(parsed.protocol) ? parsed.href : null;
  } catch {
    return null;
  }
}
