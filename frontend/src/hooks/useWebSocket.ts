/**
 * WebSocket hook for real-time ticket updates.
 *
 * Connects to the Django Channels WebSocket endpoint with JWT auth, handles
 * automatic reconnection, and invalidates React Query caches when ticket
 * events arrive.
 *
 * Keeps the connection healthy through idle proxies (Cloudflare, Caddy) with
 * an app-level ping/pong heartbeat and detects silently-dead connections by
 * timing out pongs.
 */

import { useEffect, useRef, useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { useAuthStore } from "@/store/authStore";
import { useOrgStore } from "@/store/orgStore";

/** Event types sent by the backend WebSocket consumer. */
interface TicketCreatedEvent {
  event: "ticket.created";
  ticket_id: string;
  reference: string;
  title: string;
  priority: string;
}

interface TicketUpdatedEvent {
  event: "ticket.updated";
  ticket_id: string;
  reference: string;
  status: string;
  priority: string;
}

interface MessageCreatedEvent {
  event: "message.created";
  ticket_id: string;
  message_id: string;
  reference: string;
  message_type: string;
}

interface MessageDeletedEvent {
  event: "message.deleted";
  ticket_id: string;
  message_id: string;
  reference: string;
}

interface PongEvent {
  type: "pong";
}

type WebSocketEvent =
  | TicketCreatedEvent
  | TicketUpdatedEvent
  | MessageCreatedEvent
  | MessageDeletedEvent
  | PongEvent;

const MAX_RECONNECT_ATTEMPTS = 10;
const BASE_RECONNECT_DELAY = 500;
const MAX_RECONNECT_DELAY = 15_000;

const debug = (...args: unknown[]): void => {
  if (
    typeof window !== "undefined" &&
    window.localStorage?.getItem("__WS_DEBUG__")
  ) {
    // eslint-disable-next-line no-console
    console.debug("[WS]", ...args);
  }
};

/** Send a ping this often — must be shorter than any proxy idle timeout. */
const HEARTBEAT_INTERVAL_MS = 25_000;

/** If no pong (or any other message) within this window, kill the socket. */
const HEARTBEAT_TIMEOUT_MS = 10_000;

function buildWsUrl(token: string, orgId: string | null): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = window.location.host;
  const params = new URLSearchParams({ token });
  if (orgId) params.set("org", orgId);
  return `${protocol}//${host}/ws/tickets/?${params.toString()}`;
}

/**
 * Close a socket we no longer want. If it's still CONNECTING, wait until it
 * opens before closing — closing a pending socket produces a noisy
 * "WebSocket is closed before the connection is established" console warning.
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

export type WebSocketStatus = "connecting" | "open" | "closed";

export function useWebSocket(): WebSocketStatus {
  const queryClient = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const [status, setStatus] = useState<WebSocketStatus>("closed");
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  const heartbeatIntervalRef = useRef<ReturnType<typeof setInterval> | undefined>(
    undefined,
  );
  const heartbeatTimeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );

  const accessToken = useAuthStore((s) => s.accessToken);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const activeOrgId = useOrgStore((s) => s.activeOrgId);

  const handleEvent = useCallback(
    (data: WebSocketEvent) => {
      if ("type" in data) return; // pong, ignore

      switch (data.event) {
        case "ticket.created":
          void queryClient.refetchQueries({ queryKey: ["tickets"] });
          void queryClient.refetchQueries({ queryKey: ["ticketStats"] });
          toast(`New ticket ${data.reference}: ${data.title}`, {
            icon: "\uD83C\uDFAB",
            duration: 5000,
          });
          break;

        case "ticket.updated":
          void queryClient.refetchQueries({
            queryKey: ["ticket", data.ticket_id],
          });
          void queryClient.refetchQueries({ queryKey: ["tickets"] });
          void queryClient.refetchQueries({ queryKey: ["ticketStats"] });
          break;

        case "message.created":
          void queryClient.refetchQueries({
            queryKey: ["ticket", data.ticket_id],
          });
          void queryClient.refetchQueries({ queryKey: ["tickets"] });
          if (data.message_type !== "internal_note") {
            toast(`New reply on ${data.reference}`, {
              icon: "\uD83D\uDCAC",
              duration: 4000,
            });
          }
          break;

        case "message.deleted":
          void queryClient.refetchQueries({
            queryKey: ["ticket", data.ticket_id],
          });
          void queryClient.refetchQueries({ queryKey: ["tickets"] });
          break;
      }
    },
    [queryClient],
  );

  const clearHeartbeat = useCallback(() => {
    if (heartbeatIntervalRef.current) {
      clearInterval(heartbeatIntervalRef.current);
      heartbeatIntervalRef.current = undefined;
    }
    if (heartbeatTimeoutRef.current) {
      clearTimeout(heartbeatTimeoutRef.current);
      heartbeatTimeoutRef.current = undefined;
    }
  }, []);

  const connect = useCallback(() => {
    if (!accessToken || !isAuthenticated) return;

    // Tear down any existing socket. Tag it so its onclose knows it was
    // retired by us and does not schedule a reconnect — scoped to the socket
    // object so a stale onclose from a previous tear-down can't cancel the
    // heartbeat of the new socket.
    const prev = wsRef.current as (WebSocket & { _retired?: boolean }) | null;
    if (prev) {
      retire(prev);
      wsRef.current = null;
    }
    clearHeartbeat();

    const url = buildWsUrl(accessToken, activeOrgId);
    setStatus("connecting");
    const ws = new WebSocket(url) as WebSocket & { _retired?: boolean };
    wsRef.current = ws;

    ws.onopen = () => {
      debug("open");
      setStatus("open");
      reconnectAttemptsRef.current = 0;

      heartbeatIntervalRef.current = setInterval(() => {
        if (ws.readyState !== WebSocket.OPEN) return;
        try {
          ws.send(JSON.stringify({ type: "ping" }));
          debug("ping sent");
        } catch {
          return;
        }

        if (heartbeatTimeoutRef.current) {
          clearTimeout(heartbeatTimeoutRef.current);
        }
        heartbeatTimeoutRef.current = setTimeout(() => {
          if (wsRef.current === ws && ws.readyState === WebSocket.OPEN) {
            debug("heartbeat timeout — closing");
            ws.close(4000, "Heartbeat timeout");
          }
        }, HEARTBEAT_TIMEOUT_MS);
      }, HEARTBEAT_INTERVAL_MS);
    };

    ws.onmessage = (event) => {
      if (heartbeatTimeoutRef.current) {
        clearTimeout(heartbeatTimeoutRef.current);
        heartbeatTimeoutRef.current = undefined;
      }

      try {
        const data = JSON.parse(event.data) as WebSocketEvent;
        debug("recv", data);
        handleEvent(data);
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onclose = (event) => {
      debug("close", { code: event.code, reason: event.reason, retired: ws._retired });
      // If this socket was retired (replaced by a newer one, or closed by
      // the effect cleanup), do not touch shared state or reconnect.
      if (ws._retired) return;

      if (wsRef.current === ws) {
        wsRef.current = null;
        clearHeartbeat();
        setStatus("closed");
      }

      if (!useAuthStore.getState().isAuthenticated) return;

      if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
        const delay = Math.min(
          BASE_RECONNECT_DELAY * Math.pow(2, reconnectAttemptsRef.current),
          MAX_RECONNECT_DELAY,
        );
        reconnectAttemptsRef.current += 1;
        debug("reconnecting in", delay, "ms");

        reconnectTimeoutRef.current = setTimeout(() => {
          connect();
        }, delay);
      }
    };

    ws.onerror = () => {
      // onclose will handle reconnection
    };
  }, [accessToken, isAuthenticated, activeOrgId, handleEvent, clearHeartbeat]);

  useEffect(() => {
    if (isAuthenticated && accessToken) {
      connect();
    }

    const onVisibility = () => {
      if (document.visibilityState !== "visible") return;
      if (!useAuthStore.getState().isAuthenticated) return;
      const ws = wsRef.current;
      if (!ws || ws.readyState === WebSocket.CLOSED) {
        // Reset backoff so a returning user reconnects immediately.
        reconnectAttemptsRef.current = 0;
        if (reconnectTimeoutRef.current) {
          clearTimeout(reconnectTimeoutRef.current);
          reconnectTimeoutRef.current = undefined;
        }
        connect();
      }
    };

    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("online", onVisibility);

    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("online", onVisibility);

      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      clearHeartbeat();
      if (wsRef.current) {
        retire(wsRef.current as WebSocket & { _retired?: boolean });
        wsRef.current = null;
      }
    };
  }, [isAuthenticated, accessToken, activeOrgId, connect, clearHeartbeat]);

  return status;
}
