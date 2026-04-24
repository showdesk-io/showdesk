/**
 * Widget WebSocket Client — Real-time agent replies.
 *
 * Connects to ws/widget/?token=<api_token>&session=<session_id>.
 * Handles reconnect with exponential backoff, app-level ping/pong
 * heartbeat, dead-link detection and resume-on-visibility.
 */

import type { ChatMessage } from "../types";

export type MessageHandler = (msg: ChatMessage) => void;
export type ConnectionHandler = (connected: boolean) => void;

const HEARTBEAT_INTERVAL_MS = 25_000;
const HEARTBEAT_TIMEOUT_MS = 10_000;

/**
 * Close a socket we no longer want. Defers the close until the socket has
 * actually connected, otherwise the browser logs "WebSocket is closed before
 * the connection is established."
 */
function retire(ws: WebSocket & { _retired?: boolean }): void {
  ws._retired = true;
  const closeNow = () => {
    try {
      ws.close(1000, "Retired");
    } catch {
      // ignore
    }
  };
  if (ws.readyState === WebSocket.CONNECTING) {
    ws.addEventListener("open", closeNow, { once: true });
    ws.addEventListener("error", closeNow, { once: true });
  } else if (ws.readyState === WebSocket.OPEN) {
    closeNow();
  }
}

export class WidgetWebSocket {
  private ws: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatInterval: ReturnType<typeof setInterval> | null = null;
  private heartbeatTimeout: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelay = 1000;
  private maxReconnectDelay = 30000;
  private intentionalClose = false;

  public onMessage: MessageHandler | null = null;
  public onConnectionChange: ConnectionHandler | null = null;

  private wsUrl: string | null = null;
  private visibilityHandlerBound = false;

  connect(apiUrl: string, token: string, sessionId: string): void {
    this.intentionalClose = false;
    // Derive WS URL: http(s)://host/api/v1 → ws(s)://host/ws/widget/
    // Handle both absolute and relative API URLs.
    const url = new URL(apiUrl, window.location.origin);
    const protocol = url.protocol === "https:" ? "wss:" : "ws:";
    this.wsUrl =
      `${protocol}//${url.host}/ws/widget/?token=${token}&session=${sessionId}`;
    this._bindVisibility();
    this._connect();
  }

  disconnect(): void {
    this.intentionalClose = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this._clearHeartbeat();
    if (this.ws) {
      retire(this.ws as WebSocket & { _retired?: boolean });
      this.ws = null;
    }
  }

  private _bindVisibility(): void {
    if (this.visibilityHandlerBound) return;
    this.visibilityHandlerBound = true;
    const onWake = () => {
      if (document.visibilityState !== "visible") return;
      if (this.intentionalClose) return;
      if (!this.ws || this.ws.readyState === WebSocket.CLOSED) {
        this.reconnectDelay = 1000;
        if (this.reconnectTimer) {
          clearTimeout(this.reconnectTimer);
          this.reconnectTimer = null;
        }
        this._connect();
      }
    };
    document.addEventListener("visibilitychange", onWake);
    window.addEventListener("online", onWake);
  }

  private _clearHeartbeat(): void {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
    if (this.heartbeatTimeout) {
      clearTimeout(this.heartbeatTimeout);
      this.heartbeatTimeout = null;
    }
  }

  private _connect(): void {
    if (!this.wsUrl) return;

    // Retire any socket that's still lingering so its onclose won't trigger
    // a second reconnect cycle or clear the new socket's heartbeat.
    const prev = this.ws as (WebSocket & { _retired?: boolean }) | null;
    if (prev) {
      retire(prev);
      this.ws = null;
    }

    this._clearHeartbeat();

    let ws: WebSocket & { _retired?: boolean };
    try {
      ws = new WebSocket(this.wsUrl) as WebSocket & { _retired?: boolean };
    } catch {
      this._scheduleReconnect();
      return;
    }
    this.ws = ws;

    ws.onopen = () => {
      this.reconnectDelay = 1000;
      this.onConnectionChange?.(true);

      this.heartbeatInterval = setInterval(() => {
        if (ws.readyState !== WebSocket.OPEN) return;
        try {
          ws.send(JSON.stringify({ type: "ping" }));
        } catch {
          return;
        }
        if (this.heartbeatTimeout) clearTimeout(this.heartbeatTimeout);
        this.heartbeatTimeout = setTimeout(() => {
          if (this.ws === ws && ws.readyState === WebSocket.OPEN) {
            ws.close(4000, "Heartbeat timeout");
          }
        }, HEARTBEAT_TIMEOUT_MS);
      }, HEARTBEAT_INTERVAL_MS);
    };

    ws.onmessage = (event) => {
      if (this.heartbeatTimeout) {
        clearTimeout(this.heartbeatTimeout);
        this.heartbeatTimeout = null;
      }

      try {
        const data = JSON.parse(event.data);
        if (data.type === "pong") return;
        if (data.event === "message.created" && this.onMessage) {
          this.onMessage({
            id: data.message_id,
            ticketId: data.ticket_id,
            body: data.body || "",
            bodyType: data.body_type || "text",
            senderType: data.sender_type || "agent",
            senderName: data.sender_name || "",
            attachments: [],
            createdAt: data.created_at || new Date().toISOString(),
            _status: "sent",
          });
        }
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onclose = () => {
      if (ws._retired) return;
      if (this.ws === ws) {
        this._clearHeartbeat();
        this.ws = null;
      }
      this.onConnectionChange?.(false);
      if (!this.intentionalClose) {
        this._scheduleReconnect();
      }
    };

    ws.onerror = () => {
      // onclose will fire after this
    };
  }

  private _scheduleReconnect(): void {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.reconnectDelay = Math.min(
        this.reconnectDelay * 2,
        this.maxReconnectDelay,
      );
      this._connect();
    }, this.reconnectDelay);
  }
}
