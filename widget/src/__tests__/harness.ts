/**
 * Boots a fresh copy of the widget against a fake API and a fake WebSocket.
 *
 * The widget keeps its state at module level, so each boot imports it anew. Time is
 * faked: `tick` runs what was due, and answers with a `delay` arrive when it says so.
 */

import { vi } from "vitest";

export interface Call {
  url: string;
  method: string;
  body: any;
  form: FormData | null;
  session: string | undefined;
}

export interface Answer {
  status: number;
  data: unknown;
}

export class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  /** Off, a socket stays in CONNECTING until a test calls `open()`. */
  static autoOpen = true;

  readyState = FakeWebSocket.CONNECTING;
  closed = false;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  private listeners: Array<{ type: string; fn: () => void; once: boolean }> = [];

  constructor(public url: string) {
    if (FakeWebSocket.autoOpen) setTimeout(() => this.open(), 0);
  }

  open(): void {
    if (this.readyState !== FakeWebSocket.CONNECTING) return;
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
    this.emit("open");
  }

  addEventListener(type: string, fn: () => void, options?: { once?: boolean }): void {
    this.listeners.push({ type, fn, once: Boolean(options?.once) });
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.();
  }

  private emit(type: string): void {
    for (const listener of this.listeners.filter((l) => l.type === type)) {
      if (listener.once) this.listeners.splice(this.listeners.indexOf(listener), 1);
      listener.fn();
    }
  }
}

export interface FakeApi {
  /** Return an answer to replace the default one, on a session request. */
  session?: (call: Call) => Answer | null | undefined;
  /** Conversations by session id. */
  history?: Record<string, unknown[]>;
  conversation?: (call: Call) => Answer;
}

const DEFAULT_CONVERSATION: Answer = {
  status: 200,
  data: {
    ticket_id: "t1",
    reference: "T-1",
    status: "open",
    messages: [
      {
        id: "m1",
        ticket: "t1",
        body: "hello",
        body_type: "text",
        sender_type: "user",
        sender_name: "",
        attachments: [],
        created_at: "2026-01-01T00:00:00Z",
      },
    ],
  },
};

/** The backend, as far as the widget can tell: a hash identifies, the rest doesn't. */
export function fakeApi(extra: FakeApi = {}): (call: Call) => Answer {
  let anonymous = 0;
  let messages = 0;
  return (call) => {
    if (call.url.includes("widget_session")) {
      const answer = extra.session?.(call);
      if (answer) return answer;
      const external = call.body.user_hash ? call.body.external_user_id : "";
      const sessionId = external
        ? `sess-${external}`
        : (call.body.session_id ?? `anon-${++anonymous}`);
      return {
        status: 201,
        data: { session_id: sessionId, name: "", email: "", external_user_id: external ?? "" },
      };
    }
    if (call.url.includes("widget_history")) {
      return { status: 200, data: extra.history?.[call.session ?? ""] ?? [] };
    }
    if (call.url.includes("widget_conversation")) {
      return extra.conversation?.(call) ?? DEFAULT_CONVERSATION;
    }
    if (call.url.includes("widget_message")) {
      messages += 1;
      return {
        status: 201,
        data: {
          ticket_id: "t1",
          message_id: `m${messages}`,
          reference: "T-1",
          created_at: "2026-01-01T00:00:00Z",
        },
      };
    }
    return { status: 200, data: {} };
  };
}

const originalConsole = { error: console.error, warn: console.warn, info: console.info };

export async function boot(api: FakeApi = {}) {
  vi.useRealTimers();
  vi.resetModules();
  document.head.innerHTML = "";
  document.body.innerHTML = "";
  localStorage.clear();
  console.error = vi.fn();
  console.warn = vi.fn();
  console.info = vi.fn();

  const calls: Call[] = [];
  const sockets: FakeWebSocket[] = [];
  const server = { handler: fakeApi(api), delay: 0 };

  vi.stubGlobal("fetch", async (url: unknown, init: RequestInit = {}) => {
    const body = init.body;
    const call: Call = {
      url: String(url),
      method: init.method ?? "GET",
      body: typeof body === "string" ? JSON.parse(body) : undefined,
      form: body instanceof FormData ? body : null,
      session: (init.headers as Record<string, string> | undefined)?.["X-Widget-Session"],
    };
    calls.push(call);
    if (server.delay) await new Promise((resolve) => setTimeout(resolve, server.delay));
    const answer = server.handler(call);
    return {
      ok: answer.status < 400,
      status: answer.status,
      json: async () => answer.data,
    };
  });
  vi.stubGlobal(
    "WebSocket",
    class extends FakeWebSocket {
      constructor(url: string) {
        super(url);
        sockets.push(this);
      }
    },
  );

  const widget = await import("../widget");
  vi.useFakeTimers();

  return {
    widget,
    calls,
    sockets,
    server,
    /** Session creations and resumes. */
    posts: () => calls.filter((c) => c.url.includes("widget_session") && c.method === "POST"),
    /** Messages and attachments sent. */
    sent: () => calls.filter((c) => /widget_message(_attachment)?\/$/.test(c.url)),
    conversations: () => calls.filter((c) => c.url.includes("widget_conversation")),
    histories: () => calls.filter((c) => c.url.includes("widget_history")),
    openSockets: () => sockets.filter((s) => !s.closed),
  };
}

export type Booted = Awaited<ReturnType<typeof boot>>;

export function teardown(): void {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.doUnmock("../recorder/screen-recorder");
  FakeWebSocket.autoOpen = true;
  Object.assign(console, originalConsole);
}

/** Let time pass, and whatever was waiting on it run. */
export const tick = (ms = 20) => vi.advanceTimersByTimeAsync(ms);

export const storedId = () => localStorage.getItem("showdesk_session_id");

export const bubbles = () => document.querySelectorAll("[data-message-id]");

export const textarea = () => document.querySelector("textarea") as HTMLTextAreaElement;

/** Type a message and press Enter, without waiting for what follows. */
export function pressSend(text: string): void {
  const input = textarea();
  input.value = text;
  input.dispatchEvent(new Event("input"));
  input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
}

export async function sendText(text: string): Promise<void> {
  pressSend(text);
  await tick();
}

export const panelText = () =>
  (document.querySelector(".sd-panel-content") as HTMLElement).textContent ?? "";

export function openHistoryTab(): void {
  const tabs = Array.from(document.querySelectorAll<HTMLElement>(".sd-tab"));
  tabs.find((tab) => tab.textContent?.includes("History"))?.click();
}

/** A conversation as `widget_history` returns it. */
export function historyItem(id: string, title: string, status = "resolved", unread = 0) {
  return {
    id,
    reference: `T-${id}`,
    title,
    status,
    unread_count: unread,
    last_message_at: "2026-01-01T00:00:00Z",
    last_message_preview: title,
  };
}
