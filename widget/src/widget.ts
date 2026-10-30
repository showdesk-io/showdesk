/**
 * Showdesk Widget — Entry Point
 *
 * A single, self-contained JavaScript file that can be embedded in any
 * website. Zero dependencies, zero installation required.
 *
 * v2: Messaging-style interface (WhatsApp-like chat).
 *
 * Usage:
 *   <script src="https://showdesk.io/widget.js"
 *           data-token="org-api-token"
 *           data-position="bottom-right"
 *           data-color="#6366F1"
 *           data-navigation-mode="spa"
 *           data-user-id="user-123"
 *           data-user-name="John Doe"
 *           data-user-email="john@example.com"
 *           data-user-hash="hmac-sha256-hex"
 *           data-user-email-hash="hmac-sha256-hex">
 *   </script>
 *
 * For multi-page sites (non-SPA), add data-navigation-mode="mpa"
 * to use popup-based recording that survives page navigation.
 *
 * Or programmatically:
 *   Showdesk.init({ token: "org-api-token", navigationMode: "mpa" });
 *   Showdesk.open(); // Bind to your own button
 */

import { installConsoleCollector } from "./collectors/console-collector";
import { installNetworkCollector } from "./collectors/network-collector";

// Install collectors immediately at script load — before init(), before any user interaction.
// This captures errors that occurred before the user opened the widget.
installConsoleCollector();
installNetworkCollector();

import { createButton, updateBadge } from "./ui/button";
import {
  createModal,
  destroyModal,
  getStore,
  initSession,
  switchSession,
} from "./ui/modal";
import { reattachPopupIfNeeded } from "./ui/chat/chat-view";
import { injectStyles } from "./ui/styles";
import { clearSession as clearStoredSession } from "./session/session-manager";
import type {
  NavigationMode,
  ShowdeskCompany,
  ShowdeskConfig,
  ShowdeskUserIdentity,
} from "./types";

let isInitialized = false;
let config: ShowdeskConfig;

/**
 * Derive the API base URL from the widget script tag's `src` attribute.
 * Priority: data-api-url > origin from src > /api/v1 (same-origin fallback).
 */
function getApiUrl(scriptTag: HTMLScriptElement | null): string {
  // 1. Explicit data-api-url attribute
  const explicit = scriptTag?.dataset["apiUrl"];
  if (explicit) return explicit;

  // 2. Derive origin from script src (e.g. src="https://help.example.com/cdn/widget.js")
  if (scriptTag?.src) {
    try {
      const url = new URL(scriptTag.src);
      return `${url.origin}/api/v1`;
    } catch {
      // malformed src — fall through
    }
  }

  // 3. Same-origin fallback
  return "/api/v1";
}

/**
 * Build a ShowdeskUserIdentity from data-user-* attributes on the script tag.
 * Returns undefined if no user attributes are found.
 */
function buildUserFromDataAttrs(
  el: HTMLScriptElement | null,
): ShowdeskUserIdentity | undefined {
  if (!el) return undefined;
  const id = el.dataset["userId"];
  const name = el.dataset["userName"];
  const email = el.dataset["userEmail"];
  const hash = el.dataset["userHash"];
  const emailHash = el.dataset["userEmailHash"];
  if (!id && !name && !email) return undefined;
  return { id, name, email, hash, emailHash };
}

/**
 * Initialize the Showdesk widget.
 */
function init(userConfig: Partial<ShowdeskConfig> = {}): void {
  if (isInitialized) {
    console.warn("[Showdesk] Widget is already initialized.");
    return;
  }

  // Read config from script tag data attributes or user config
  const scriptTag = document.querySelector(
    'script[data-token][src*="widget"]',
  ) as HTMLScriptElement | null;

  config = {
    token: userConfig.token ?? scriptTag?.dataset["token"] ?? "",
    apiUrl: userConfig.apiUrl ?? getApiUrl(scriptTag),
    position:
      userConfig.position ??
      (scriptTag?.dataset["position"] as "bottom-right" | "bottom-left") ??
      "bottom-right",
    color: userConfig.color ?? scriptTag?.dataset["color"] ?? "#6366F1",
    label: userConfig.label ?? scriptTag?.dataset["label"] ?? "Help",
    greeting:
      userConfig.greeting ??
      scriptTag?.dataset["greeting"] ??
      "How can we help you?",
    hideButton: userConfig.hideButton ?? false,
    user: userConfig.user ?? buildUserFromDataAttrs(scriptTag),
    company: userConfig.company,
    navigationMode:
      userConfig.navigationMode ??
      (scriptTag?.dataset["navigationMode"] as NavigationMode) ??
      "spa",
  };

  if (!config.token) {
    console.error(
      "[Showdesk] No organization token provided. " +
        'Set data-token on the script tag or pass { token: "..." } to Showdesk.init().',
    );
    return;
  }

  // Inject styles into the page
  injectStyles(config.color);

  // Create the floating button (unless hidden for programmatic use)
  if (!config.hideButton) {
    createButton(config, () => open());
  }

  // Subscribe to unread count changes for the FAB badge
  const store = getStore();
  store.subscribe(() => {
    updateBadge(store.state.unreadCount);
  });

  isInitialized = true;
  console.info("[Showdesk] Widget initialized.");

  // Eagerly bootstrap the session + conversation history so the FAB badge
  // can show unread replies before the user opens the panel. No-op on retry.
  void initSession(config);

  // MPA mode: probe for an existing popup recorder from a previous page load
  if (config.navigationMode === "mpa") {
    reattachPopupIfNeeded(store, config, () => open());
  }
}

/**
 * Open the messaging panel.
 */
function open(): void {
  if (!isInitialized) {
    console.error("[Showdesk] Widget not initialized. Call Showdesk.init() first.");
    return;
  }
  createModal(config);
}

/**
 * Set or update user identity after initialization.
 *
 * - With an id and a hash (a login without a reload): the session is created again
 *   and replaces the stored one. An anonymous conversation carries on under the
 *   identified session; another user's is taken off the screen.
 * - With nothing, or without a hash when a user was identified (a logout): same as
 *   reset(). The widget is gone until the next init().
 * - Otherwise, on an anonymous session (a name or an email without a hash): only
 *   updates the local config, sent to the server by the next init().
 *
 * `company` belongs to this user: leaving it out sends none, so that a user can't
 * inherit the company of the previous one.
 */
function setUser(
  user?: ShowdeskUserIdentity | null,
  company?: ShowdeskCompany,
): void {
  if (!isInitialized) {
    console.warn("[Showdesk] Call init() before setUser()");
    return;
  }
  const hasIdentity = Boolean(String(user?.id ?? "") && user?.hash);
  const isEmpty = !String(user?.id ?? "") && !user?.name && !user?.email;
  // The hash covers a session still being created, not known here yet.
  const wasIdentified = Boolean(
    config.user?.hash || getStore().state.session?.externalUserId,
  );
  if (!hasIdentity && (isEmpty || wasIdentified)) {
    reset();
    return;
  }
  config.user = user ?? undefined;
  config.company = company;
  if (hasIdentity) {
    void switchSession(config);
  }
}

/**
 * Destroy the widget and clean up DOM elements.
 */
function destroy(): void {
  destroyModal();
  const container = document.getElementById("showdesk-widget-container");
  if (container) {
    container.remove();
  }
  isInitialized = false;
}

/**
 * Reset the widget: destroy the UI AND clear the stored session id.
 * Call this when the embedding app's user identity changes (e.g. logout)
 * so the next init() does not resume the previous user's conversation.
 * setUser() without an identity does the same. Call init() to bring the widget back.
 */
function reset(): void {
  destroy();
  clearStoredSession();
}

// Auto-initialize if script tag has data-token
if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", () => {
    const scriptTag = document.querySelector(
      'script[data-token][src*="widget"]',
    );
    if (scriptTag) {
      init();
    }
  });
}

// Export public API
export { init, open, destroy, reset, setUser };
