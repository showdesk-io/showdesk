/**
 * Modal — Messaging panel (replaces the old wizard modal).
 *
 * Docked panel (bottom-right/left) with tab bar and content area.
 * Structure:
 *   Header (greeting + close)
 *   Tab bar (Chat | History)
 *   Content area (chat view or history view)
 */

import {
  createOrResumeSession,
  fetchConversation,
  fetchHistory,
  markConversationRead,
} from "../api/chat-api";
import { WidgetWebSocket } from "../api/websocket";
import {
  getStoredSessionId,
  storeSessionId,
} from "../session/session-manager";
import { createWidgetStore } from "../state/widget-state";
import type { WidgetState, WidgetStore } from "../state/widget-state";
import type {
  ChatMessage,
  ConversationSummary,
  ShowdeskConfig,
  WidgetSession,
  WidgetTab,
} from "../types";
import { renderChatView, reattachPopupIfNeeded } from "./chat/chat-view";
import { renderHistoryView } from "./history/history-view";

/** Statuses that mean a conversation is still live (not resolved/closed). */
const OPEN_STATUSES = new Set(["open", "in_progress", "waiting"]);

/** Sum of unread replies across conversations still considered open. */
function countOpenUnread(conversations: ConversationSummary[]): number {
  return conversations
    .filter((c) => OPEN_STATUSES.has(c.status))
    .reduce((sum, c) => sum + (c.unreadCount || 0), 0);
}

/** Pick the open conversation with the freshest unread reply, if any. */
function pickConversationToResume(
  conversations: ConversationSummary[],
): ConversationSummary | null {
  const candidates = conversations
    .filter((c) => OPEN_STATUSES.has(c.status) && c.unreadCount > 0)
    .sort((a, b) => {
      const ta = a.lastMessageAt ? Date.parse(a.lastMessageAt) : 0;
      const tb = b.lastMessageAt ? Date.parse(b.lastMessageAt) : 0;
      return tb - ta;
    });
  return candidates[0] ?? null;
}

const EMPTY_CONVERSATION: Partial<WidgetState> = {
  activeTicketId: null,
  activeTicketReference: null,
  messages: [],
};

/** What the store holds of the user whose session it is. */
const EMPTY_VIEW: Partial<WidgetState> = {
  ...EMPTY_CONVERSATION,
  conversations: [],
  unreadCount: 0,
  isLoading: false,
  contactNudgeDismissed: false,
  contactNudgeShown: false,
};

let currentPanel: HTMLElement | null = null;
let store: WidgetStore | null = null;
let ws: WidgetWebSocket | null = null;
let unsubscribe: (() => void) | null = null;

/** True only when the panel is mounted AND visible. Drives whether
 *  incoming messages are treated as "seen" or bumped to the unread badge. */
function isPanelVisible(): boolean {
  return currentPanel != null && currentPanel.style.display !== "none";
}

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
 * Bumped by each session request and by destroyModal: whatever an older request
 * gets back is stale, and must neither be stored nor touch the view.
 */
let sessionRun = 0;
let runInFlight: Promise<void> | null = null;

/**
 * Initialize the session and WebSocket connection.
 * Called eagerly on widget init so the FAB badge reflects unread replies
 * even before the panel is opened, and again when the panel opens: the second
 * call joins the request in flight rather than creating a second session.
 */
export function initSession(config: ShowdeskConfig): Promise<void> {
  if (getStore().state.session) return Promise.resolve();
  return runInFlight ?? startSessionRun(config);
}

/**
 * Create the session again for the identity now in `config`, whatever is in flight.
 *
 * The session returned replaces the stored one. An anonymous session's conversation
 * moved to it on the server (a login), so it stays on screen until refreshed. Another
 * user's goes at once, even if the request then fails: that user is no longer here.
 */
export function switchSession(config: ShowdeskConfig): Promise<void> {
  const s = getStore();
  const owner = s.state.session?.externalUserId;
  if (owner && owner !== String(config.user?.id ?? "")) {
    ws?.disconnect();
    s.update({ session: null, isConnected: false, ...EMPTY_VIEW });
    renderActiveTab(config);
  }
  return startSessionRun(config);
}

function startSessionRun(config: ShowdeskConfig): Promise<void> {
  const run = ++sessionRun;
  const promise = runSession(config, run).finally(() => {
    if (runInFlight === promise) runInFlight = null;
  });
  runInFlight = promise;
  return promise;
}

async function runSession(config: ShowdeskConfig, run: number): Promise<void> {
  const s = getStore();

  try {
    const session = await createOrResumeSession(config, getStoredSessionId());
    if (run !== sessionRun) return;
    storeSessionId(session.sessionId);

    if (config.user?.hash && !session.externalUserId) {
      console.warn("[Showdesk] User hash refused: the session stays anonymous.");
    }

    const previous = s.state.session;
    const changed = previous?.sessionId !== session.sessionId;
    s.update({ session });

    if (changed) {
      connectWebSocket(config, s, session.sessionId);
      if (previous) await refreshActiveConversation(config, s, session, run);
      if (run !== sessionRun) return;
    }

    // Prefetch conversation list so the FAB badge is accurate on page load
    // and the panel can auto-open the most recent unread reply.
    try {
      const conversations = await fetchHistory(config, session.sessionId);
      if (run !== sessionRun) return;
      s.update({
        conversations,
        unreadCount: countOpenUnread(conversations),
      });
    } catch {
      // Silent — history is a nice-to-have on boot; user can still open the panel.
    }

    // The history tab shows what it fetched when rendered, not the store.
    if (changed && previous && s.state.activeTab === "history") {
      renderActiveTab(config);
    }
  } catch (err) {
    if (run === sessionRun) {
      console.error("[Showdesk] Session initialization failed:", err);
    }
  }
}

/** Point the shared WebSocket at a session, instead of the one it was on. */
function connectWebSocket(
  config: ShowdeskConfig,
  s: WidgetStore,
  sessionId: string,
): void {
  const socket = getWebSocket();
  socket.disconnect();
  socket.onMessage = (msg: ChatMessage) => {
    // Skip user's own messages — already handled by optimistic UI
    if (msg.senderType === "user") return;

    // The user is actively looking at this ticket only if the panel is
    // open AND the ticket is the currently-displayed one. Otherwise the
    // message counts as unread, even on the "last active" ticket.
    const isViewing =
      isPanelVisible() && msg.ticketId === s.state.activeTicketId;

    if (isViewing) {
      // Don't add duplicates
      const exists = s.state.messages.some((m) => m.id === msg.id);
      if (!exists) {
        s.update({ messages: [...s.state.messages, msg] });
        // Keep the server-side read marker current so a refresh doesn't
        // re-raise the badge for this reply.
        void markConversationRead(config, sessionId, msg.ticketId);
      }
    } else {
      // Widget is closed or the reply is on another ticket — bump the
      // badge and keep the conversations list in sync so
      // pickConversationToResume picks the right ticket next open.
      const nextConversations = s.state.conversations.map((c) =>
        c.id === msg.ticketId
          ? {
              ...c,
              unreadCount: c.unreadCount + 1,
              lastMessageAt: msg.createdAt,
              lastMessagePreview: msg.body || c.lastMessagePreview,
            }
          : c,
      );
      s.update({
        unreadCount: s.state.unreadCount + 1,
        conversations: nextConversations,
      });
    }
  };
  socket.onConnectionChange = (connected: boolean) => {
    s.update({ isConnected: connected });
  };
  socket.connect(config.apiUrl, config.token, sessionId);
}

/**
 * Reload the open conversation under a new session, keeping what's still being sent.
 * If the session can't read it, it wasn't moved: back to a new conversation.
 */
async function refreshActiveConversation(
  config: ShowdeskConfig,
  s: WidgetStore,
  session: WidgetSession,
  run: number,
): Promise<void> {
  const ticketId = s.state.activeTicketId;
  if (!ticketId) return;
  try {
    const data = await fetchConversation(config, session.sessionId, ticketId);
    if (run !== sessionRun || s.state.activeTicketId !== ticketId) return;
    const unsent = s.state.messages.filter((m) => m._status !== "sent");
    s.update({
      activeTicketReference: data.reference,
      messages: [...data.messages, ...unsent],
    });
  } catch {
    if (run !== sessionRun || s.state.activeTicketId !== ticketId) return;
    s.update(EMPTY_CONVERSATION);
    renderActiveTab(config);
  }
}

/**
 * Bring the panel into the "just opened" state: if there's a ticket with
 * unread replies, jump to it and refetch its messages. Otherwise leave the
 * existing active conversation in place. Always resets the FAB badge.
 *
 * Called from both first-open (panel creation) and re-show (panel was
 * hidden) so a close/reopen cycle behaves like a fresh open.
 */
function resumeActiveConversation(config: ShowdeskConfig): void {
  const s = getStore();
  const resume = pickConversationToResume(s.state.conversations);

  if (resume) {
    const switchingTicket = resume.id !== s.state.activeTicketId;
    s.update({
      activeTab: "chat",
      activeTicketId: resume.id,
      activeTicketReference: resume.reference,
      // Only wipe messages when we're jumping to a different ticket —
      // otherwise keep them visible while we refetch.
      messages: switchingTicket ? [] : s.state.messages,
      isLoading: true,
      conversations: s.state.conversations.map((c) =>
        c.id === resume.id ? { ...c, unreadCount: 0 } : c,
      ),
    });
    const session = s.state.session;
    if (session) {
      fetchConversation(config, session.sessionId, resume.id)
        .then((data) => {
          // The user changed meanwhile: this is no longer theirs to see.
          if (s.state.session?.sessionId !== session.sessionId) return;
          s.update({
            activeTicketId: data.ticketId,
            activeTicketReference: data.reference,
            messages: data.messages,
            isLoading: false,
          });
          void markConversationRead(config, session.sessionId, resume.id);
        })
        .catch(() => s.update({ isLoading: false }));
    }
  }

  // Reset unread count — the user is now looking at the panel.
  s.update({ unreadCount: 0 });
}

/**
 * Open the messaging panel.
 */
export function createModal(config: ShowdeskConfig): void {
  // If already open, just bring to front — but still refresh resume state
  // so fresh replies don't sit behind a stale active conversation.
  if (currentPanel) {
    currentPanel.style.display = "";
    resumeActiveConversation(config);
    return;
  }

  const s = getStore();

  resumeActiveConversation(config);

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
  void initSession(config);

  // MPA mode: check if a popup recorder is still alive from a previous page
  if (config.navigationMode === "mpa") {
    reattachPopupIfNeeded(s, config, () => createModal(config));
  }
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

/** Render the active tab again, if the panel exists. */
function renderActiveTab(config: ShowdeskConfig): void {
  const content = currentPanel?.querySelector(
    ".sd-panel-content",
  ) as HTMLElement | null;
  if (content) renderTab(content, getStore(), config);
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
  // A session coming back now must not be stored over a reset, nor reconnect.
  sessionRun++;
  runInFlight = null;
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
