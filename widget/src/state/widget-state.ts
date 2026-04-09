/**
 * Widget State — Simple reactive state management (pub/sub).
 *
 * No framework dependency. Components subscribe to state changes
 * and are notified when state is mutated via `update()`.
 */

import type {
  ChatMessage,
  ConversationSummary,
  WidgetSession,
  WidgetTab,
} from "../types";

export interface WidgetState {
  activeTab: WidgetTab;
  session: WidgetSession | null;

  /** Current active conversation ticket ID. */
  activeTicketId: string | null;
  activeTicketReference: string | null;
  messages: ChatMessage[];

  /** History tab data. */
  conversations: ConversationSummary[];

  /** UI flags. */
  isConnected: boolean;
  isLoading: boolean;
  contactNudgeDismissed: boolean;
  contactNudgeShown: boolean;

  /** Unread badge count (agent replies while modal closed). */
  unreadCount: number;
}

type Listener = () => void;

export interface WidgetStore {
  state: WidgetState;
  subscribe: (fn: Listener) => () => void;
  update: (partial: Partial<WidgetState>) => void;
}

export function createWidgetStore(): WidgetStore {
  const listeners = new Set<Listener>();

  const state: WidgetState = {
    activeTab: "chat",
    session: null,
    activeTicketId: null,
    activeTicketReference: null,
    messages: [],
    conversations: [],
    isConnected: false,
    isLoading: false,
    contactNudgeDismissed: false,
    contactNudgeShown: false,
    unreadCount: 0,
  };

  function subscribe(fn: Listener): () => void {
    listeners.add(fn);
    return () => listeners.delete(fn);
  }

  function update(partial: Partial<WidgetState>): void {
    Object.assign(state, partial);
    listeners.forEach((fn) => fn());
  }

  return { state, subscribe, update };
}
