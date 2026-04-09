/**
 * Session Manager — Persists widget session ID in localStorage.
 *
 * Falls back to in-memory storage if localStorage is unavailable
 * (e.g. cross-origin iframes, private browsing restrictions).
 */

const STORAGE_KEY = "showdesk_session_id";

let memoryFallback: string | null = null;

export function getStoredSessionId(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return memoryFallback;
  }
}

export function storeSessionId(id: string): void {
  memoryFallback = id;
  try {
    localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // localStorage unavailable — memory fallback is already set
  }
}

export function clearSession(): void {
  memoryFallback = null;
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}
