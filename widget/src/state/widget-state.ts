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
  /** The active conversation is only seen through the history: no writing there. */
  activeTicketReadOnly: boolean;
  /** A conversation closed too long ago to reopen: the ticket ID, until another opens. */
  closedTicketId: string | null;
  messages: ChatMessage[];

  /** History tab data. */
  conversations: ConversationSummary[];

  /** UI flags. */
  isConnected: boolean;
  isLoading: boolean;
  contactNudgeDismissed: boolean;

  /** Unread badge count (agent replies while modal closed). */
  unreadCount: number;

  /** When this session last asked for an email code (ms), null if it hasn't. */
  emailCodeSentAt: number | null;
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
    activeTicketReadOnly: false,
    closedTicketId: null,
    messages: [],
    conversations: [],
    isConnected: false,
    isLoading: false,
    contactNudgeDismissed: false,
    unreadCount: 0,
    emailCodeSentAt: null,
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
