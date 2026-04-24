/**
 * History View — List of past conversations.
 *
 * Clicking a conversation loads its messages in the chat view.
 * "New conversation" button starts a fresh thread.
 */

import {
  fetchHistory,
  fetchConversation,
  markConversationRead,
} from "../../api/chat-api";
import type { WidgetStore } from "../../state/widget-state";
import type { ShowdeskConfig, ConversationSummary } from "../../types";

export function renderHistoryView(
  container: HTMLElement,
  store: WidgetStore,
  config: ShowdeskConfig,
): void {
  container.innerHTML = "";

  const wrapper = document.createElement("div");
  wrapper.className = "sd-history-view";

  // New conversation button
  const newBtn = document.createElement("button");
  newBtn.className = "sd-btn-new-conversation";
  newBtn.textContent = "+ New conversation";
  newBtn.onclick = () => {
    store.update({
      activeTab: "chat",
      activeTicketId: null,
      activeTicketReference: null,
      messages: [],
    });
  };
  wrapper.appendChild(newBtn);

  // Loading state
  const list = document.createElement("div");
  list.className = "sd-history-list";
  wrapper.appendChild(list);

  container.appendChild(wrapper);

  // Fetch history
  loadHistory(list, store, config);
}

async function loadHistory(
  listEl: HTMLElement,
  store: WidgetStore,
  config: ShowdeskConfig,
): Promise<void> {
  const session = store.state.session;
  if (!session) {
    listEl.innerHTML = `<div class="sd-history-empty">No conversations yet.</div>`;
    return;
  }

  listEl.innerHTML = `<div class="sd-history-loading">Loading...</div>`;

  try {
    const conversations = await fetchHistory(config, session.sessionId);
    store.update({ conversations });

    listEl.innerHTML = "";

    if (conversations.length === 0) {
      listEl.innerHTML = `<div class="sd-history-empty">No conversations yet.</div>`;
      return;
    }

    for (const conv of conversations) {
      listEl.appendChild(renderConversationItem(conv, store, config));
    }
  } catch {
    listEl.innerHTML = `<div class="sd-history-empty">Could not load history.</div>`;
  }
}

function renderConversationItem(
  conv: ConversationSummary,
  store: WidgetStore,
  config: ShowdeskConfig,
): HTMLElement {
  const item = document.createElement("div");
  item.className = "sd-history-item";

  const header = document.createElement("div");
  header.className = "sd-history-item-header";

  const title = document.createElement("span");
  title.className = "sd-history-item-title";
  title.textContent = conv.title || conv.reference;

  const statusBadge = document.createElement("span");
  statusBadge.className = `sd-status-badge sd-status-${conv.status}`;
  statusBadge.textContent = conv.status.replace("_", " ");

  header.appendChild(title);
  header.appendChild(statusBadge);

  const preview = document.createElement("div");
  preview.className = "sd-history-item-preview";
  preview.textContent = conv.lastMessagePreview || "No messages";

  const meta = document.createElement("div");
  meta.className = "sd-history-item-meta";
  if (conv.lastMessageAt) {
    meta.textContent = formatDate(conv.lastMessageAt);
  }
  if (conv.unreadCount > 0) {
    const badge = document.createElement("span");
    badge.className = "sd-unread-badge";
    badge.textContent = String(conv.unreadCount);
    meta.appendChild(badge);
  }

  item.appendChild(header);
  item.appendChild(preview);
  item.appendChild(meta);

  item.onclick = () => openConversation(conv, store, config);

  return item;
}

async function openConversation(
  conv: ConversationSummary,
  store: WidgetStore,
  config: ShowdeskConfig,
): Promise<void> {
  const session = store.state.session;
  if (!session) return;

  store.update({ isLoading: true });

  try {
    const data = await fetchConversation(
      config,
      session.sessionId,
      conv.id,
    );
    store.update({
      activeTab: "chat",
      activeTicketId: data.ticketId,
      activeTicketReference: data.reference,
      messages: data.messages,
      isLoading: false,
      conversations: store.state.conversations.map((c) =>
        c.id === conv.id ? { ...c, unreadCount: 0 } : c,
      ),
      unreadCount: Math.max(0, store.state.unreadCount - conv.unreadCount),
    });
    void markConversationRead(config, session.sessionId, conv.id);
  } catch {
    store.update({ isLoading: false });
  }
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diff = now.getTime() - d.getTime();

    if (diff < 60000) return "Just now";
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    return d.toLocaleDateString();
  } catch {
    return "";
  }
}
