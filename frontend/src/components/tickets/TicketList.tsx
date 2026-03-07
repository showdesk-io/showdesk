/**
 * Ticket list component with filtering and status indicators.
 *
 * Optimized for agent speed: scan-friendly layout, color-coded
 * priorities, relative timestamps.
 */

import { Link } from "react-router-dom";
import { clsx } from "clsx";
import type { TicketListItem, TicketPriority, TicketStatus } from "@/types";

const statusColors: Record<TicketStatus, string> = {
  open: "bg-blue-100 text-blue-800",
  in_progress: "bg-yellow-100 text-yellow-800",
  waiting: "bg-gray-100 text-gray-800",
  resolved: "bg-green-100 text-green-800",
  closed: "bg-gray-100 text-gray-500",
};

const priorityColors: Record<TicketPriority, string> = {
  low: "bg-gray-100 text-gray-600",
  medium: "bg-blue-100 text-blue-600",
  high: "bg-orange-100 text-orange-600",
  urgent: "bg-red-100 text-red-600",
};

interface TicketListProps {
  tickets: TicketListItem[];
  isLoading: boolean;
}

export function TicketList({ tickets, isLoading }: TicketListProps) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
      </div>
    );
  }

  if (tickets.length === 0) {
    return (
      <div className="py-12 text-center text-gray-500">
        No tickets found.
      </div>
    );
  }

  return (
    <div className="divide-y divide-gray-200">
      {tickets.map((ticket) => (
        <Link
          key={ticket.id}
          to={`/tickets/${ticket.id}`}
          className="flex items-center gap-4 px-6 py-4 transition-colors hover:bg-gray-50"
        >
          {/* Priority indicator */}
          <span
            className={clsx(
              "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
              priorityColors[ticket.priority],
            )}
          >
            {ticket.priority}
          </span>

          {/* Ticket info */}
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono text-gray-400">
                {ticket.reference}
              </span>
              <h3 className="truncate text-sm font-medium text-gray-900">
                {ticket.title}
              </h3>
            </div>
            <p className="mt-0.5 text-xs text-gray-500">
              {ticket.requester_detail?.email ?? ticket.requester_email}
            </p>
          </div>

          {/* Status badge */}
          <span
            className={clsx(
              "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
              statusColors[ticket.status],
            )}
          >
            {ticket.status.replace("_", " ")}
          </span>

          {/* Message count */}
          <span className="text-xs text-gray-400">
            {ticket.message_count} msg
          </span>
        </Link>
      ))}
    </div>
  );
}
