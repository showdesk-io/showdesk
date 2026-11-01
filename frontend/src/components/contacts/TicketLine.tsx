/**
 * A ticket in a contact's timeline or a company's tickets.
 */

import { Link } from "react-router";
import { StatusBadge } from "@/components/common/StatusBadge";
import type { TicketListItem } from "@/types";
import { formatDateTime } from "./format";

export function TicketLine({ ticket }: { ticket: TicketListItem }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <Link
          to={`/tickets/${ticket.id}`}
          className="break-words text-sm font-medium text-gray-900 hover:text-primary-700"
        >
          <span className="mr-2 font-mono text-xs text-gray-500">{ticket.reference}</span>{" "}
          {ticket.title}
        </Link>
        <p className="mt-1 text-xs text-gray-400">{formatDateTime(ticket.updated_at)}</p>
      </div>
      <StatusBadge status={ticket.status} />
    </div>
  );
}
