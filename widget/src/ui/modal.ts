/**
 * Modal — Messaging panel (replaces the old wizard modal).
 *
 * Docked panel (bottom-right/left) with tab bar and content area.
 * Structure:
 *   Header (greeting + close)
 *   Tab bar (Chat | History)
 *   Content area (chat view or history view)
 */

import { createOrResumeSession } from "../api/chat-api";
import { WidgetWebSocket } from "../api/websocket";
import {
  getStoredSessionId,
  storeSessionId,
} from "../session/session-manager";
import { createWidgetStore } from "../state/widget-state";
import type { WidgetStore } from "../state/widget-state";
import type { ChatMessage, ShowdeskConfig, WidgetTab } from "../types";
import { renderChatView } from "./chat/chat-view";
import { renderHistoryView } from "./history/history-view";

let currentPanel: HTMLElement | null = null;
let store: WidgetStore | null = null;
let ws: WidgetWebSocket | null = null;
let unsubscribe: (() => void) | null = null;

/**
 * Get or create the shared widget store.
 */
export function getStore(): WidgetStore {
  if (!store) {
    store = createWidgetStore();
  }
  return store;
}

/**
 * Get or create the shared WebSocket instance.
 */
export function getWebSocket(): WidgetWebSocket {
  if (!ws) {
    ws = new WidgetWebSocket();
  }
  return ws;
}

/**
 * Initialize the session and WebSocket connection.
 * Called once on first widget open.
 */
export async function initSession(config: ShowdeskConfig): Promise<void> {
  const s = getStore();
  if (s.state.session) return; // Already initialized

  try {
    const existingSessionId = getStoredSessionId();
    const session = await createOrResumeSession(config, existingSessionId);
    storeSessionId(session.sessionId);
    s.update({ session });

    // Connect WebSocket
    const socket = getWebSocket();
    socket.onMessage = (msg: ChatMessage) => {
      // Skip user's own messages — already handled by optimistic UI
      if (msg.senderType === "user") return;

      if (msg.ticketId === s.state.activeTicketId) {
        // Don't add duplicates
        const exists = s.state.messages.some((m) => m.id === msg.id);
        if (!exists) {
          s.update({ messages: [...s.state.messages, msg] });
        }
      } else {
        // Agent replied on a different conversation — increment unread
        s.update({ unreadCount: s.state.unreadCount + 1 });
      }
    };
    socket.onConnectionChange = (connected: boolean) => {
      s.update({ isConnected: connected });
    };
    socket.connect(config.apiUrl, config.token, session.sessionId);
  } catch (err) {
    console.error("[Showdesk] Session initialization failed:", err);
  }
}

/**
 * Open the messaging panel.
 */
export function createModal(config: ShowdeskConfig): void {
  // If already open, just bring to front
  if (currentPanel) {
    currentPanel.style.display = "";
    return;
  }

  const s = getStore();

  // Reset unread count when opening
  s.update({ unreadCount: 0 });

  // Create panel
  const panel = document.createElement("div");
  panel.id = "sd-panel";
  panel.className = `sd-panel sd-panel-${config.position}`;

  // Header
  const header = document.createElement("div");
  header.className = "sd-panel-header";

  const greeting = document.createElement("div");
  greeting.className = "sd-panel-greeting";
  greeting.textContent = config.greeting;

  const closeBtn = document.createElement("button");
  closeBtn.className = "sd-panel-close";
  closeBtn.innerHTML = "×";
  closeBtn.title = "Close";
  closeBtn.onclick = () => closeModal();

  header.appendChild(greeting);
  header.appendChild(closeBtn);

  // Tab bar
  const tabBar = document.createElement("div");
  tabBar.className = "sd-tab-bar";

  const chatTab = createTabBtn("chat", "💬 Chat", s, config);
  const historyTab = createTabBtn("history", "📋 History", s, config);

  tabBar.appendChild(chatTab);
  tabBar.appendChild(historyTab);

  // Content area
  const content = document.createElement("div");
  content.className = "sd-panel-content";

  panel.appendChild(header);
  panel.appendChild(tabBar);
  panel.appendChild(content);

  // Get or create container
  let container = document.getElementById("showdesk-widget-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "showdesk-widget-container";
    document.body.appendChild(container);
  }
  container.appendChild(panel);
  currentPanel = panel;

  // Render active tab
  renderTab(content, s, config);

  // Subscribe to tab changes — re-render content when tab switches programmatically
  let lastTab = s.state.activeTab;
  unsubscribe = s.subscribe(() => {
    chatTab.classList.toggle("sd-tab-active", s.state.activeTab === "chat");
    historyTab.classList.toggle(
      "sd-tab-active",
      s.state.activeTab === "history",
    );
    if (s.state.activeTab !== lastTab) {
      lastTab = s.state.activeTab;
      const c = currentPanel?.querySelector(
        ".sd-panel-content",
      ) as HTMLElement | null;
      if (c) renderTab(c, s, config);
    }
  });

  // Close on Escape
  const escHandler = (e: KeyboardEvent) => {
    if (e.key === "Escape") closeModal();
  };
  document.addEventListener("keydown", escHandler);
  (panel as unknown as Record<string, unknown>)._escHandler = escHandler;

  // Initialize session (async, don't block render)
  initSession(config);
}

function createTabBtn(
  tab: WidgetTab,
  label: string,
  s: WidgetStore,
  config: ShowdeskConfig,
): HTMLElement {
  const el = document.createElement("button");
  el.className = `sd-tab ${s.state.activeTab === tab ? "sd-tab-active" : ""}`;
  el.textContent = label;
  el.onclick = () => {
    if (s.state.activeTab === tab) return;
    s.update({ activeTab: tab });
    const content = currentPanel?.querySelector(
      ".sd-panel-content",
    ) as HTMLElement | null;
    if (content) {
      renderTab(content, s, config);
    }
  };
  return el;
}

function renderTab(
  content: HTMLElement,
  s: WidgetStore,
  config: ShowdeskConfig,
): void {
  content.innerHTML = "";
  if (s.state.activeTab === "chat") {
    renderChatView(content, s, config, () => createModal(config));
  } else {
    renderHistoryView(content, s, config);
  }
}

/**
 * Close the messaging panel (hide, don't destroy).
 */
export function closeModal(): void {
  if (currentPanel) {
    currentPanel.style.display = "none";
    const escHandler = (currentPanel as unknown as Record<string, unknown>)
      ._escHandler as EventListener;
    if (escHandler) {
      document.removeEventListener("keydown", escHandler);
    }
  }
}

/**
 * Destroy the panel and clean up.
 */
export function destroyModal(): void {
  if (unsubscribe) {
    unsubscribe();
    unsubscribe = null;
  }
  if (ws) {
    ws.disconnect();
    ws = null;
  }
  if (currentPanel) {
    currentPanel.remove();
    currentPanel = null;
  }
  store = null;
}
