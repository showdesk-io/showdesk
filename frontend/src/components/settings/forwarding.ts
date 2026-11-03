/**
 * Helpers of the email settings tab: what the UI trusts of a Gmail confirmation.
 */

/** The hosts of Gmail's forwarding confirmation links, as the backend checks them. */
const CONFIRMATION_HOSTS = new Set(["mail.google.com", "mail-settings.google.com"]);

/**
 * `url` if it's an https link to one of Gmail's confirmation hosts, else null.
 *
 * The backend already checks it, but the link comes from a mail whose sender can be
 * forged: the UI never links anywhere else, whatever the API sends.
 */
export function safeConfirmationUrl(url: string): string | null {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (
    parsed.protocol !== "https:" ||
    !CONFIRMATION_HOSTS.has(parsed.hostname) ||
    parsed.port !== "" ||
    parsed.username !== "" ||
    parsed.password !== ""
  ) {
    return null;
  }
  return parsed.href;
}
