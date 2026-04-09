/**
 * Widget WebSocket Client — Real-time agent replies.
 *
 * Connects to ws/widget/?token=<api_token>&session=<session_id>.
 * Handles reconnect with exponential backoff.
 */

import type { ChatMessage } from "../types";

export type MessageHandler = (msg: ChatMessage) => void;
export type ConnectionHandler = (connected: boolean) => void;

export class WidgetWebSocket {
  private ws: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelay = 1000;
  private maxReconnectDelay = 30000;
  private intentionalClose = false;

  public onMessage: MessageHandler | null = null;
  public onConnectionChange: ConnectionHandler | null = null;

  private wsUrl: string | null = null;

  connect(apiUrl: string, token: string, sessionId: string): void {
    this.intentionalClose = false;
    // Derive WS URL: http(s)://host/api/v1 → ws(s)://host/ws/widget/
    const url = new URL(apiUrl);
    const protocol = url.protocol === "https:" ? "wss:" : "ws:";
    this.wsUrl =
      `${protocol}//${url.host}/ws/widget/?token=${token}&session=${sessionId}`;
    this._connect();
  }

  disconnect(): void {
    this.intentionalClose = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  private _connect(): void {
    if (!this.wsUrl) return;

    try {
      this.ws = new WebSocket(this.wsUrl);
    } catch {
      this._scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.reconnectDelay = 1000;
      this.onConnectionChange?.(true);
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
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

    this.ws.onclose = () => {
      this.onConnectionChange?.(false);
      if (!this.intentionalClose) {
        this._scheduleReconnect();
      }
    };

    this.ws.onerror = () => {
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
