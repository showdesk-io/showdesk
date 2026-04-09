/**
 * WebSocket hook for real-time ticket updates.
 *
 * Connects to the Django Channels WebSocket endpoint with JWT auth,
 * handles automatic reconnection, and invalidates React Query caches
 * when ticket events arrive.
 */

import { useEffect, useRef, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { useAuthStore } from "@/store/authStore";

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

type WebSocketEvent =
  | TicketCreatedEvent
  | TicketUpdatedEvent
  | MessageCreatedEvent
  | MessageDeletedEvent;

/** Max reconnection attempts before giving up. */
const MAX_RECONNECT_ATTEMPTS = 10;

/** Base delay (ms) for exponential backoff reconnection. */
const BASE_RECONNECT_DELAY = 1000;

/**
 * Build the WebSocket URL with JWT token as query parameter.
 */
function buildWsUrl(token: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = window.location.host;
  return `${protocol}//${host}/ws/tickets/?token=${encodeURIComponent(token)}`;
}

/**
 * Hook that maintains a WebSocket connection for real-time ticket updates.
 *
 * - Connects when the user is authenticated
 * - Disconnects on logout
 * - Auto-reconnects with exponential backoff
 * - Invalidates React Query caches on relevant events
 * - Shows toast notifications for new tickets and messages
 */
export function useWebSocket() {
  const queryClient = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const accessToken = useAuthStore((s) => s.accessToken);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  const handleEvent = useCallback(
    (data: WebSocketEvent) => {
      switch (data.event) {
        case "ticket.created":
          // Refetch ticket list and dashboard stats immediately
          void queryClient.refetchQueries({ queryKey: ["tickets"] });
          void queryClient.refetchQueries({ queryKey: ["ticketStats"] });
          toast(`New ticket ${data.reference}: ${data.title}`, {
            icon: "\uD83C\uDFAB",
            duration: 5000,
          });
          break;

        case "ticket.updated":
          // Refetch the specific ticket, ticket list, and stats
          void queryClient.refetchQueries({
            queryKey: ["ticket", data.ticket_id],
          });
          void queryClient.refetchQueries({ queryKey: ["tickets"] });
          void queryClient.refetchQueries({ queryKey: ["ticketStats"] });
          break;

        case "message.created":
          // Refetch the ticket detail (includes messages) immediately
          void queryClient.refetchQueries({
            queryKey: ["ticket", data.ticket_id],
          });
          void queryClient.refetchQueries({ queryKey: ["tickets"] });
          // Only toast for non-internal messages
          if (data.message_type !== "internal_note") {
            toast(`New reply on ${data.reference}`, {
              icon: "\uD83D\uDCAC",
              duration: 4000,
            });
          }
          break;

        case "message.deleted":
          // Refetch the ticket detail so the deleted message disappears
          void queryClient.refetchQueries({
            queryKey: ["ticket", data.ticket_id],
          });
          void queryClient.refetchQueries({ queryKey: ["tickets"] });
          break;
      }
    },
    [queryClient],
  );

  const connect = useCallback(() => {
    if (!accessToken || !isAuthenticated) return;

    // Close existing connection
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    const url = buildWsUrl(accessToken);
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      reconnectAttemptsRef.current = 0;
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as WebSocketEvent;
        handleEvent(data);
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onclose = (event) => {
      wsRef.current = null;

      // Don't reconnect if closed cleanly (logout) or not authenticated
      if (event.code === 1000 || !useAuthStore.getState().isAuthenticated) {
        return;
      }

      // Exponential backoff reconnection
      if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
        const delay =
          BASE_RECONNECT_DELAY *
          Math.pow(2, reconnectAttemptsRef.current);
        reconnectAttemptsRef.current += 1;

        reconnectTimeoutRef.current = setTimeout(() => {
          connect();
        }, delay);
      }
    };

    ws.onerror = () => {
      // onclose will handle reconnection
    };
  }, [accessToken, isAuthenticated, handleEvent]);

  useEffect(() => {
    if (isAuthenticated && accessToken) {
      connect();
    }

    return () => {
      // Clean close on unmount
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close(1000, "Component unmounted");
        wsRef.current = null;
      }
    };
  }, [isAuthenticated, accessToken, connect]);
}
