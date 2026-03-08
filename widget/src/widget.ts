/**
 * Showdesk Widget — Entry Point
 *
 * A single, self-contained JavaScript file that can be embedded in any
 * website. Zero dependencies, zero installation required. The widget
 * captures the user's screen, webcam, and microphone to submit
 * video-first support tickets.
 *
 * Usage:
 *   <script src="https://showdesk.io/widget.js"
 *           data-token="org-api-token"
 *           data-position="bottom-right"
 *           data-color="#6366F1">
 *   </script>
 *
 * Or programmatically:
 *   Showdesk.init({ token: "org-api-token" });
 *   Showdesk.open(); // Bind to your own button
 */

import { installConsoleCollector } from "./collectors/console-collector";
import { installNetworkCollector } from "./collectors/network-collector";

// Install collectors immediately at script load — before init(), before any user interaction.
// This captures errors that occurred before the user opened the widget.
installConsoleCollector();
installNetworkCollector();

import { createButton } from "./ui/button";
import { createModal } from "./ui/modal";
import { injectStyles } from "./ui/styles";
import { captureContext } from "./api/context";
import type { ShowdeskConfig, ShowdeskUserIdentity } from "./types";

let isInitialized = false;
let config: ShowdeskConfig;

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
    apiUrl:
      userConfig.apiUrl ??
      scriptTag?.dataset["apiUrl"] ??
      "https://showdesk.io/api/v1",
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
    user: userConfig.user,
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

  isInitialized = true;
  console.info("[Showdesk] Widget initialized.");
}

/**
 * Open the ticket submission modal.
 */
function open(): void {
  if (!isInitialized) {
    console.error("[Showdesk] Widget not initialized. Call Showdesk.init() first.");
    return;
  }

  const context = captureContext();
  createModal(config, context);
}

/**
 * Set or update user identity after initialization.
 */
function setUser(user: ShowdeskUserIdentity): void {
  if (!isInitialized) {
    console.warn("[Showdesk] Call init() before setUser()");
    return;
  }
  config.user = user;
}

/**
 * Destroy the widget and clean up DOM elements.
 */
function destroy(): void {
  const container = document.getElementById("showdesk-widget-container");
  if (container) {
    container.remove();
  }
  isInitialized = false;
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
export { init, open, destroy, setUser };
